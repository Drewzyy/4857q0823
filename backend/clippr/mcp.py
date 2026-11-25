"""The MCP server Muse connects to: Model Context Protocol over Streamable HTTP, on 127.0.0.1 (this computer only,
the default) or this computer's Tailscale address (Settings), never on every network.

POST http://<address>:<port>/mcp with `Authorization: Bearer <token>`. The token is made on first run and kept in
a file in the data folder only your user can read; Settings shows it. The port is fixed (Settings, default 47821): if it's taken the
server doesn't start and says so in the log, rather than moving somewhere Muse won't look.

Every tool is a thin layer over the app's own code: reads come from the same database the app shows, writes go
through the same rules (posting.py) and the same edit and job flow as the app's buttons (apply_edit, the jobs
queue), each with an audit entry saying Muse did it. No tool deletes anything, and none returns a credential.
"""
from __future__ import annotations

import hmac
import re
import json
import os
import logging
import secrets as pysecrets
import socket
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response
from sqlalchemy import select
from sqlalchemy.orm import object_session

from . import dropbox, posting, preedit, screen
from .audit import audit
from .api.analytics import HOSTS, link_post
from .api.clips import _live_outputs, apply_edit
from .api.deps import ApiError
from .api.system import load_settings
from .models import Campaign, CampaignClip, Clip, ClipOutput, Creator, DestinationAccount, MetricSnapshot, SourceAccount
from .routing import destination_creator_ids, page_kinds, source_creator_ids
from .schemas import ClipEdit

log = logging.getLogger("clippr.mcp")
TOKEN_FILE = "mcp-token"  # in the data folder, readable by your user only
PROTOCOL = "2025-06-18"
ACTOR = "muse"


def token(ctx) -> str:
    """The bridge's token: made once, kept in a file only your user can read. Not the OS keychain: every update is a
    newly signed app to macOS, so reading a keychain item an older version saved asks for permission and waits for
    an answer. At startup that hung the app after updates."""
    path = ctx.config.data_dir / TOKEN_FILE
    try:
        t = path.read_text().strip()
    except OSError:
        t = ""
    if not t:
        t = pysecrets.token_urlsafe(32)
        path.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as f:
            f.write(t)
    return t


class ToolError(Exception):
    pass


# ---- what tools return -------------------------------------------------------------------------------------

def _out(o: ClipOutput) -> dict:
    d = o.destination
    return {"output_id": o.id, "platform": o.platform, "destination": {"id": d.id, "handle": d.handle, "name": d.display_name} if d else None,
            "file_path": str(Path(o.file_path).resolve()) if o.file_path else None,
            "file_exists": bool(o.file_path and Path(o.file_path).exists()), "render_state": o.render_state,
            "caption": o.description, "title": o.title, "review": o.review, "review_note": o.review_note,
            "post_url": o.post_url, "status": o.status, "quality": o.quality, **_dropbox(o)}


def _dropbox(o: ClipOutput) -> dict:
    """Where the video is in Dropbox, for Muse to fetch it there: status queued | uploading | uploaded | failed, or None."""
    d = dropbox.status_for(object_session(o), o.file_path)
    return {"dropbox_status": d["status"] if d else None, "dropbox_path": d["path"] if d and d["status"] == "uploaded" else None}


def _clip(c: Clip, outs: list[ClipOutput]) -> dict:
    e = c.edit or {}
    ref = c.reference
    return {"clip_id": c.id, "title": c.title, "created_at": c.created_at.isoformat() if c.created_at else None,
            "creator": {"id": c.creator.id, "name": c.creator.name, "kind": c.creator.content_kind} if c.creator else None,
            "kind": (c.content or {}).get("kind"),
            "source": {"platform": ref.platform, "channel": ref.source.username if ref and ref.source else None, "url": ref.url} if ref
            else {"platform": "stream", "channel": None, "url": c.vod_url},
            "duration": round(float(e.get("end", 0)) - float(e.get("start", 0)), 2) if e else c.source_duration,
            "virality_score": (c.grade or {}).get("score"), "virality_tier": (c.grade or {}).get("tier"),
            "safety": (c.safety or {}).get("status"), "outputs": [_out(o) for o in outs]}


def _clips(s, wanted: Callable[[ClipOutput], bool]) -> list[dict]:
    cfg = load_settings(s).posting
    res = []
    for c in s.scalars(select(Clip).where(Clip.status == "ready").order_by(Clip.created_at.desc()).limit(200)).unique():
        if posting.held_back(c, cfg.min_virality):
            continue  # quarantined, no permission, or under the score: never offered
        outs = [o for o in _live_outputs(s, c.id) if wanted(o) and (o.quality or {}).get("status") != "fail"]  # broken files never offered
        if outs:
            res.append(_clip(c, outs))
    return res


def _get(s, cid: int) -> Clip:
    c = s.get(Clip, cid)
    if not c or not c.edit:
        raise ToolError(f"No clip {cid}")
    return c


def _pick_output(s, c: Clip, destination_id: int | None) -> ClipOutput:
    outs = _live_outputs(s, c.id)
    if destination_id is not None:
        outs = [o for o in outs if o.destination_id == destination_id]
    if len(outs) != 1:
        pages = ", ".join(f"{o.destination_id} ({o.destination.handle if o.destination else o.platform})" for o in _live_outputs(s, c.id))
        raise ToolError(f"Say which page (destination_id): {pages or 'this clip has no pages'}")
    return outs[0]


# ---- tools ---------------------------------------------------------------------------------------------------

def list_ready_clips(ctx, a):
    with ctx.db.session() as s:
        return _clips(s, lambda o: o.status == "ready" and o.render_state == "ready")


def list_clips_for_review(ctx, a):
    with ctx.db.session() as s:
        return _clips(s, lambda o: o.status == "ready" and o.review == "pending" and o.render_state == "ready")


def get_clip(ctx, a):
    with ctx.db.session() as s:
        c = _get(s, a["clip_id"])
        return {**_clip(c, _live_outputs(s, c.id)), "held_back": posting.held_back(c, load_settings(s).posting.min_virality)}


def review_clip(ctx, a):
    with ctx.db.session() as s:
        c = _get(s, a["clip_id"])
        e = ClipEdit.model_validate({"video_height": 0, **(c.edit or {})}).model_dump()
        headline = next((t["text"] for t in e["texts"] if t.get("headline") or t.get("box")), None)
        return {**_clip(c, _live_outputs(s, c.id)), "held_back": posting.held_back(c, load_settings(s).posting.min_virality),
                "transcript": " ".join(w["text"] for w in c.words or []),
                "words": [{"start": round(w["start"], 2), "end": round(w["end"], 2), "text": w["text"]} for w in c.words or []],
                "hook_text": headline, "hook": e.get("hook"), "trim": {"start": e["start"], "end": e["end"]},
                "footage_seconds": round((c.source_start or 0) + (c.source_duration or 0) + 3, 1),
                "grade": c.grade, "safety": c.safety}


def get_safety_check(ctx, a):
    with ctx.db.session() as s:
        c = _get(s, a["clip_id"])
    return ctx.pipeline.check_safety(c.id) or {}


def list_quarantined_clips(ctx, a):
    with ctx.db.session() as s:
        return [{"clip_id": c.id, "title": c.title, "flags": [f for f in (c.safety or {}).get("flags", []) if f["level"] == "fail"]}
                for c in s.scalars(select(Clip).where(Clip.status == "ready")).unique() if (c.safety or {}).get("status") == "fail"]


def list_sources(ctx, a):
    with ctx.db.session() as s:
        names = {c.id: c.name for c in s.scalars(select(Creator))}
        return [{"id": x.id, "platform": x.platform, "handle": x.username, "creators": [names.get(i) for i in source_creator_ids(x)],
                 "monitoring": x.monitoring == "active"} for x in s.scalars(select(SourceAccount)).unique()]


def list_destinations(ctx, a):
    from datetime import timedelta
    from sqlalchemy import func
    since = datetime.now().astimezone() - timedelta(days=1)
    with ctx.db.session() as s:
        names = {c.id: c.name for c in s.scalars(select(Creator))}
        today = dict(s.execute(select(ClipOutput.destination_id, func.count()).where(ClipOutput.uploaded_at >= since)
                               .group_by(ClipOutput.destination_id)).all())
        return [{"id": d.id, "platform": d.platform, "handle": d.handle, "name": d.display_name, "enabled": d.enabled,
                 "creators": [names.get(i) for i in destination_creator_ids(d)], "kinds": page_kinds(d),
                 "auto_post": bool((d.settings or {}).get("auto_post")), "daily_cap": int((d.settings or {}).get("daily_cap", 3)),
                 "posted_last_24h": today.get(d.id, 0)} for d in s.scalars(select(DestinationAccount)).unique()]


def list_campaigns(ctx, a):
    with ctx.db.session() as s:
        tagged: dict[int, list[int]] = {}
        for l in s.scalars(select(CampaignClip)):
            tagged.setdefault(l.campaign_id, []).append(l.clip_id)
        return [{"id": c.id, "name": c.name, "tag": c.tag, "creator": c.creator.name if c.creator else None, "live": c.status == "live",
                 "min_views": c.min_views, "required_hashtags": c.required_hashtags, "must_mention": c.must_mention, "clip_rules": c.clip_rules, "join_url": c.join_url,
                 "tagged_clip_ids": tagged.get(c.id, [])} for c in s.scalars(select(Campaign)).unique()]


def list_funnel_routes(ctx, a):
    """Routes are worked out from each page's streamers and kinds (routing.py): one row per streamer and page."""
    with ctx.db.session() as s:
        pages = list(s.scalars(select(DestinationAccount)).unique())
        return [{"creator": c.name, "kind": c.content_kind, "destination_id": d.id, "destination": d.handle or d.display_name,
                 "on": d.enabled and c.content_kind in page_kinds(d)}
                for c in s.scalars(select(Creator)) for d in pages if c.id in destination_creator_ids(d)]


def update_clip(ctx, a):
    with ctx.db.session() as s:
        c = _get(s, a["clip_id"])
        if (c.safety or {}).get("status") == "fail":
            raise ToolError("Quarantined clips can't be edited back into review")
        changed = []
        if "caption" in a:
            for o in [_pick_output(s, c, a.get("destination_id"))] if a.get("destination_id") is not None else _live_outputs(s, c.id):
                o.description = a["caption"].strip()[:2200]
                if o.review == "approved" and not o.post_url:
                    o.review = "pending"  # approval was for the exact caption
            changed.append("caption")
        e = ClipEdit.model_validate({"video_height": 0, **(c.edit or {})}).model_dump()
        video = False
        if "trim_start" in a or "trim_end" in a:
            e["start"], e["end"] = float(a.get("trim_start", e["start"])), float(a.get("trim_end", e["end"]))
            video = True
        if "hook" in a:
            e["hook"] = a["hook"]
            video = True
        if "hook_text" in a:
            heads = [t for t in e["texts"] if t.get("headline") or t.get("box")]
            text = a["hook_text"].strip()[:200]
            if not text:  # empty: take the headline off the video
                e["texts"] = [t for t in e["texts"] if not (t.get("headline") or t.get("box"))]
            elif heads:
                heads[0]["text"] = text
            else:  # the clip had none (not every clip gets one): add it at the top for the opening seconds
                e["texts"].insert(0, {"text": text, "start": 0, "end": preedit.TITLE_SECONDS + ((e["hook"][1] - e["hook"][0]) if e.get("hook") else 0),
                                      "y_percent": preedit.HEADLINE_Y, "size": preedit.HEADLINE_SIZE, "color": "#141414", "font": "poppins",
                                      "all_caps": False, "outline": 0, "box": True, "headline": True})
            video = True
        if "destination_ids" in a:  # pages left out are taken off this clip (rejected, not deleted)
            keep = set(a["destination_ids"])
            for o in _live_outputs(s, c.id):
                if o.destination_id not in keep and o.review != "rejected":
                    posting.reject(s, o.id, ACTOR, "Not for this page (Muse)")
            changed.append("destinations")
        if video:
            try:
                apply_edit(s, ctx.jobs, c, ClipEdit.model_validate(e), by=ACTOR)
            except Exception as err:  # ApiError and validation alike: say why, change nothing
                raise ToolError(getattr(err, "message", str(err)))
            changed.append("video (re-rendering; the transcript is reused)")
        audit(s, "clip.updated", "clip", c.id, {"by": ACTOR, "changed": changed})
        return {"clip_id": c.id, "changed": changed}


def approve_clip(ctx, a):
    with ctx.db.session() as s:
        c = _get(s, a["clip_id"])
        o = _pick_output(s, c, a.get("destination_id"))
        when = datetime.fromisoformat(a["scheduled_at"]) if a.get("scheduled_at") else None
        o = posting.approve(s, o.id, ACTOR, watched=bool(a.get("watched")), caption=a.get("caption"), scheduled_at=when)
        return _out(o)


def reject_clip(ctx, a):
    with ctx.db.session() as s:
        c = _get(s, a["clip_id"])
        outs = [_pick_output(s, c, a["destination_id"])] if a.get("destination_id") is not None else _live_outputs(s, c.id)
        return [_out(posting.reject(s, o.id, ACTOR, a["reason"], teach=i == 0)) for i, o in enumerate(outs)]  # one note teaches once


def give_feedback(ctx, a):
    """What you think of a clip, approved or not ("good but too long"): the next clips are cut to it."""
    with ctx.db.session() as s:
        c = _get(s, a["clip_id"])
        changed = screen.learn(s, a["note"], c.id)
        audit(s, "clip.feedback", "clip", c.id, {"by": ACTOR, "note": a["note"][:200], "learned": changed})
        return {"learned": changed, "now": {k: v for k, v in screen.learned(s).items() if k != "history"}}


def get_posting_package(ctx, a):
    with ctx.db.session() as s:
        return posting.package(s, _pick_output(s, _get(s, a["clip_id"]), a.get("destination_id")).id)


def mark_posted(ctx, a):
    """Muse posted an approved video itself: record the link, which counts it as uploaded (analytics, campaigns)."""
    with ctx.db.session() as s:
        o = _pick_output(s, _get(s, a["clip_id"]), a.get("destination_id"))
        if o.review != "approved":
            raise ToolError("Approve it first")
        if not re.match(rf"^https://([\w-]+\.)?{HOSTS.get(o.platform, '')}/", a["post_url"].strip()):
            raise ToolError(f"That isn't a {o.platform.title()} link. Send the link to the post itself.")
        chk = {**posting.check_post(s, ctx.fetcher, o, a["post_url"]), "by": ACTOR}
        if chk["status"] == "failed":  # kept in the posted history as a claim that didn't hold up
            o.post_check = chk
            audit(s, "post.claim_refused", "output", o.id, {"by": ACTOR, "url": chk["url"], "reason": chk["reason"]})
        else:
            try:
                link_post(s, ctx.jobs, o, a["post_url"], ACTOR)
            except ApiError as e:
                raise ToolError(e.message)
            o.post_check = chk
            return {**_out(o), "post_check": chk}
    raise ToolError(f"Not recorded as posted: {chk['reason']}. Post the video, then send the link to the live post.")


def report_metrics(ctx, a):
    """Numbers for a post Vyral can't read itself (Instagram, Facebook, X): views, likes, comments, shares as the post
    shows them now. They feed Analytics and which clips go on to your other pages (promote_best)."""
    with ctx.db.session() as s:
        o = _pick_output(s, _get(s, a["clip_id"]), a.get("destination_id"))
        if not o.post_url:
            raise ToolError("Record the post first with mark_posted")
        nums = {k: int(a[k]) for k in ("views", "likes", "comments", "shares") if a.get(k) is not None}
        if not nums:
            raise ToolError("Send at least views")
        s.add(MetricSnapshot(output_id=o.id, source="muse", **nums))
        audit(s, "metrics.reported", "output", o.id, {"by": ACTOR, **nums})
        return {"output_id": o.id, "recorded": nums}


def set_streamer(ctx, a):
    """The clip is of another streamer than Vyral thought (the "wrong person"): move it to the right one."""
    with ctx.db.session() as s:
        c = _get(s, a["clip_id"])
        cr = s.get(Creator, a["creator_id"])
        if not cr:
            raise ToolError("No such streamer: list_sources shows them")
        cid = c.id
    return ctx.pipeline.reassign(cid, cr.id)


ID = {"clip_id": {"type": "integer"}}
DEST = {"destination_id": {"type": "integer", "description": "Which page; needed when the clip goes to more than one"}}
RO = {"readOnlyHint": True}
TOOLS: dict[str, tuple[Callable, str, dict, list[str], dict]] = {
    "list_ready_clips": (list_ready_clips, "Clips with finished videos, each page's file path, caption, review state and scores. "
                         "Quarantined clips, streamers without clip permission and low scorers are left out.", {}, [], RO),
    "list_clips_for_review": (list_clips_for_review, "Clips waiting for review (same fields as list_ready_clips).", {}, [], RO),
    "get_clip": (get_clip, "Everything about one clip: every page's video, render state, review and post URL.", ID, ["clip_id"], RO),
    "review_clip": (review_clip, "What to review: the videos, transcript with word times, caption, hook (headline and teaser), trim, "
                    "virality grade and safety check.", ID, ["clip_id"], RO),
    "get_safety_check": (get_safety_check, "Runs the safety check now: flagged categories, confidence, the moment (seconds) and "
                         "what can't be machine-checked.", ID, ["clip_id"], RO),
    "list_quarantined_clips": (list_quarantined_clips, "Clips the safety check failed, with why.", {}, [], RO),
    "list_sources": (list_sources, "Watched accounts: platform, handle, streamers, monitoring on or off.", {}, [], RO),
    "list_destinations": (list_destinations, "Pages clips post to: platform, handle, streamers, kinds, enabled, Auto-post (Muse may post approved clips without asking you first), its daily_cap and posted_last_24h: never go over the cap.", {}, [], RO),
    "list_campaigns": (list_campaigns, "Clipping campaigns: tag, streamer, live or ended, minimum views, the hashtags and names a caption "
                       "must have, where to submit, and the clips tagged to each.", {}, [], RO),
    "list_funnel_routes": (list_funnel_routes, "Which streamer's clips go to which page.", {}, [], RO),
    "update_clip": (update_clip, "Change a clip: caption (one page or all), hook_text (the headline, use only words said in the clip), "
                    "hook ([start, end] footage seconds shown first, or null), trim_start/trim_end (footage seconds), destination_ids "
                    "(pages to keep). Video changes re-render without re-transcribing; a changed video needs approving again.",
                    {**ID, **DEST, "caption": {"type": "string", "maxLength": 2200}, "hook_text": {"type": "string", "maxLength": 200, "description": "The headline on the video (top, opening seconds). Adds one if the clip has none; empty takes it off."},
                     "hook": {"type": ["array", "null"], "items": {"type": "number"}, "minItems": 2, "maxItems": 2},
                     "trim_start": {"type": "number"}, "trim_end": {"type": "number"},
                     "destination_ids": {"type": "array", "items": {"type": "integer"}}}, ["clip_id"], {}),
    "approve_clip": (approve_clip, "Approve one page's video for posting. Doesn't post it: post it yourself with get_posting_package, then call mark_posted. "
                     "watched must be true: the picture isn't machine-checked. Optional final caption and scheduled_at (ISO 8601).",
                     {**ID, **DEST, "watched": {"type": "boolean"}, "caption": {"type": "string", "maxLength": 2200},
                      "scheduled_at": {"type": "string"}}, ["clip_id", "watched"], {}),
    "reject_clip": (reject_clip, "Reject a clip (one page, or all of them) with a reason. Say it plainly (too short, too long, boring, "
                    "no context, just screaming): Vyral learns from it and cuts and screens the next clips to match.",
                    {**ID, **DEST, "reason": {"type": "string", "minLength": 1, "maxLength": 500}}, ["clip_id", "reason"], {}),
    "report_metrics": (report_metrics, "For a post Vyral can't read itself (Instagram, Facebook, X): its views, likes, comments and shares "
                       "as the post shows them now. Report them a few times over the first days: the best performers go on to your other pages.",
                       {**ID, **DEST, **{k: {"type": "integer", "minimum": 0} for k in ("views", "likes", "comments", "shares")}},
                       ["clip_id", "views"], {}),
    "set_streamer": (set_streamer, "The clip is of a different streamer than Vyral picked (wrong person): move it to the right one by their "
                     "id (list_sources). Its pages, @, hashtags and title are redone for them.",
                     {**ID, "creator_id": {"type": "integer"}}, ["clip_id", "creator_id"], {}),
    "give_feedback": (give_feedback, "Tell Vyral what you think of a clip without rejecting it (\"good but too long\", \"needs more setup\"). "
                      "It adjusts how the next clips are cut and screened; returns what changed.",
                      {**ID, "note": {"type": "string", "minLength": 1, "maxLength": 500}}, ["clip_id", "note"], {}),
    "get_posting_package": (get_posting_package, "For an approved video: post_after (don't post it before this: posts on one page are spaced out and go out in the daytime posting hours), suggested_sound (TikTok: the song your own clips use most; add it from TikTok's sound picker when posting), file path (and dropbox_path once it's in Dropbox), final caption, page, aspect ratio, duration, schedule. Post it yourself, then call mark_posted.",
                            {**ID, **DEST}, ["clip_id"], RO),
    "mark_posted": (mark_posted, "After you posted an approved video yourself: record its link. Vyral opens the link and only records it if "
                    "it's a live post on that page (TikTok, YouTube; Instagram, Facebook and X are kept as unverified). (https, on that page's platform: TikTok, "
                    "Instagram, YouTube, Facebook or X). Marks it uploaded so analytics and campaigns pick it up.",
                    {**ID, **DEST, "post_url": {"type": "string", "minLength": 8, "maxLength": 500}}, ["clip_id", "post_url"], {}),
}


def _tool_list() -> list[dict]:
    return [{"name": n, "description": d, "inputSchema": {"type": "object", "properties": p, "required": r, "additionalProperties": False},
             "annotations": {**ann, "destructiveHint": False}} for n, (_, d, p, r, ann) in TOOLS.items()]


def handle(ctx, msg: dict) -> dict | None:
    """One JSON-RPC message in, its response out (None for notifications)."""
    mid, method, params = msg.get("id"), msg.get("method", ""), msg.get("params") or {}

    def ok(result):
        return {"jsonrpc": "2.0", "id": mid, "result": result}
    if mid is None:
        return None  # notifications (initialized, cancelled) need no answer
    if method == "initialize":
        return ok({"protocolVersion": params.get("protocolVersion") or PROTOCOL, "capabilities": {"tools": {"listChanged": False}},
                   "serverInfo": {"name": "vyral", "version": "1"},
                   "instructions": "Vyral's clips. Review with review_clip, fix with update_clip, then approve_clip (only after watching) "
                                   "and get_posting_package to post it yourself, then mark_posted with the post's link. Quarantined clips are never offered."})
    if method == "ping":
        return ok({})
    if method == "tools/list":
        return ok({"tools": _tool_list()})
    if method == "tools/call":
        name, args = params.get("name"), params.get("arguments") or {}
        if name not in TOOLS:
            return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32602, "message": f"Unknown tool {name}"}}
        try:
            data = TOOLS[name][0](ctx, args)
            return ok({"content": [{"type": "text", "text": json.dumps(data, default=str)}], "structuredContent": {"result": data}, "isError": False})
        except (ToolError, posting.PostingError, KeyError, ValueError) as e:
            return ok({"content": [{"type": "text", "text": str(e) if not isinstance(e, KeyError) else f"Missing {e}"}], "isError": True})
        except Exception:
            log.exception("MCP tool %s failed", name)
            return ok({"content": [{"type": "text", "text": "Something went wrong in Vyral. Details are in the app log."}], "isError": True})
    return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": f"Unknown method {method}"}}


def create_app(ctx) -> FastAPI:
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)

    @app.post("/mcp")
    async def mcp(request: Request):
        if request.headers.get("host", "").split(":")[0] not in ("127.0.0.1", "localhost", getattr(ctx.mcp, "host", "")):
            return JSONResponse({"error": "Forbidden host"}, status_code=421)  # only the address it listens on: no DNS rebinding
        given = request.headers.get("authorization", "").removeprefix("Bearer ").strip()
        if not hmac.compare_digest(given.encode(), token(ctx).encode()):
            return JSONResponse({"error": "Missing or invalid token"}, status_code=401)
        try:
            body = await request.json()
        except ValueError:
            return JSONResponse({"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "Parse error"}}, status_code=400)
        from starlette.concurrency import run_in_threadpool  # tools touch the database and files: off the event loop
        if isinstance(body, list):
            out = [r for r in [await run_in_threadpool(handle, ctx, m) for m in body] if r]
        else:
            out = await run_in_threadpool(handle, ctx, body)
        return JSONResponse(out) if out else Response(status_code=202)

    @app.get("/mcp")
    async def no_stream():
        return Response(status_code=405)  # no server-initiated messages: plain request and response

    return app


class Server:
    """Runs the MCP app on <address>:<port> (Settings) in a background thread for as long as Vyral runs."""

    def __init__(self, ctx):
        self.ctx, self.thread, self.server, self.error = ctx, None, None, None

    def start(self) -> None:
        import uvicorn
        with self.ctx.db.session() as s:
            cfg = load_settings(s).posting
        if not cfg.mcp_enabled:
            return
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        try:
            sock.bind((cfg.mcp_host, cfg.mcp_port))
        except OSError as e:
            sock.close()
            self.error = (f"Port {cfg.mcp_port} is already in use ({e.strerror}); the MCP server for Muse is off. Pick another port in Settings."
                          if e.errno in (48, 98, 10048) else
                          f"Can't listen on {cfg.mcp_host} ({e.strerror}): is Tailscale running and is that this computer's Tailscale address?")
            log.error("MCP server not started: %s", self.error)
            return
        token(self.ctx)
        self.server = uvicorn.Server(uvicorn.Config(create_app(self.ctx), log_level="warning", access_log=False))
        self.thread = threading.Thread(target=self.server.run, kwargs={"sockets": [sock]}, name="mcp", daemon=True)
        self.thread.start()
        for _ in range(100):  # ready before anyone is told it's on
            if self.server.started or not self.thread.is_alive():
                break
            threading.Event().wait(0.05)
        self.port, self.host, self.error = cfg.mcp_port, cfg.mcp_host, None
        log.info("MCP server for Muse on http://%s:%s/mcp", cfg.mcp_host, cfg.mcp_port)

    def stop(self) -> None:
        if self.server:
            self.server.should_exit = True
            self.thread.join(timeout=5)
            self.server = None

    def restart(self) -> None:
        self.stop()
        self.start()

    def state(self) -> dict[str, Any]:
        return {"running": bool(self.server), "port": getattr(self, "port", None), "error": self.error}

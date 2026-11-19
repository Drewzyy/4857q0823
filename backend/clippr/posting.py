"""Review, approval and publishing: the one place the rules live, used by the app and by Muse (mcp.py).

The chain for each page's video: made -> safety check (safety.py) -> virality grade -> review -> approved or
rejected -> sent to Postiz (draft, scheduled or now) -> Postiz reports where it went.
- A quarantined clip (safety fail), a streamer without clip permission, or a grade under Settings' minimum never
  reaches review, whatever page it's moved to or however it's re-rendered.
- Approving needs whoever approves to have watched it (the picture isn't machine-checked: see safety.py).
- Nothing is published by approving alone, except on a page with Auto-post on: that needs 5 reviewed posts on
  the page first, a clip that passed safety outright, the daily cap not reached and the kill switch off.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .api.system import load_settings
from .audit import audit
from .models import AuditLog, Clip, ClipOutput, DestinationAccount
from .postiz import SECRET, Postiz, PostizError

UNLOCK_AFTER = 5  # reviewed posts on a page before its Auto-post can be turned on


class PostingError(Exception):
    pass


def held_back(clip: Clip, min_virality: int) -> str | None:
    """Why this clip can't be reviewed or posted, or None if it can."""
    if clip.creator and not clip.creator.clip_permission:
        return "You haven't confirmed permission to clip this streamer"
    safe = clip.safety or {}
    if safe.get("status") == "fail":
        return "Quarantined by the safety check: " + "; ".join(f["reason"] for f in safe.get("flags", []) if f["level"] == "fail")
    if not safe.get("status"):
        return "The safety check hasn't run yet"
    score = (clip.grade or {}).get("score")
    if score is None:
        return "Not graded yet"
    if score < min_virality:
        return f"Virality score {score} is under the minimum of {min_virality} (Settings)"
    return None


def reviewed_posts(s: Session, dest_id: int) -> int:
    """Videos on this page that were reviewed, approved and went out."""
    return s.scalar(select(func.count()).select_from(ClipOutput).where(
        ClipOutput.destination_id == dest_id, ClipOutput.review == "approved", ClipOutput.reviewed_by != "auto",
        (ClipOutput.postiz_state == "published") | (ClipOutput.status == "uploaded"))) or 0


def _output(s: Session, oid: int) -> tuple[ClipOutput, Clip]:
    o = s.get(ClipOutput, oid)
    if not o or o.status in ("expired", "withdrawn"):
        raise PostingError("No such video, or it has expired or its streamer is turned off")
    return o, s.get(Clip, o.clip_id)


def approve(s: Session, jobs, oid: int, actor: str, *, watched: bool, caption: str | None = None,
            scheduled_at: datetime | None = None) -> ClipOutput:
    o, clip = _output(s, oid)
    why = held_back(clip, load_settings(s).posting.min_virality)
    if why:
        raise PostingError(why)
    if not watched:
        raise PostingError("Watch the video before approving: nudity, gore and weapons on screen aren't machine-checked")
    if o.render_state == "rendering":
        raise PostingError("It's re-rendering; approve the new version when it's ready")
    if caption is not None:
        o.description = caption.strip()[:2200]
    o.review, o.review_note, o.reviewed_by, o.scheduled_at = "approved", "", actor, scheduled_at
    audit(s, "output.approved", "clip_output", oid, {"by": actor, "clip": clip.id, "scheduled": bool(scheduled_at)})
    _auto_post(s, jobs, o, clip)
    return o


def reject(s: Session, oid: int, actor: str, reason: str) -> ClipOutput:
    o, clip = _output(s, oid)
    o.review, o.review_note, o.reviewed_by = "rejected", reason.strip()[:500], actor
    audit(s, "output.rejected", "clip_output", oid, {"by": actor, "clip": clip.id, "reason": o.review_note})
    return o


def _auto_post(s: Session, jobs, o: ClipOutput, clip: Clip) -> None:
    d = o.destination
    cfg = load_settings(s).posting
    st = (d.settings or {}) if d else {}
    if not d or not st.get("auto_post") or cfg.auto_post_kill_switch or (clip.safety or {}).get("status") != "pass":
        return  # uncertain safety never auto-posts
    since = datetime.now(timezone.utc) - timedelta(days=1)
    today = s.scalar(select(func.count()).select_from(AuditLog).where(
        AuditLog.action == "output.auto_posted", AuditLog.ts >= since, AuditLog.details["page"].as_integer() == d.id)) or 0
    if today >= int(st.get("daily_cap", 3)) or reviewed_posts(s, d.id) < UNLOCK_AFTER:
        return
    audit(s, "output.auto_posted", "clip_output", o.id, {"page": d.id})
    jobs.enqueue("postiz.send", {"output_id": o.id, "mode": "now"}, max_attempts=2, session=s)


def can_turn_on_auto_post(s: Session, dest: DestinationAccount) -> str | None:
    n = reviewed_posts(s, dest.id)
    return None if n >= UNLOCK_AFTER else f"Auto-post unlocks after {UNLOCK_AFTER} reviewed posts on this page ({n} so far)"


def package(s: Session, oid: int) -> dict:
    """Everything needed to post an approved video by hand or through Muse."""
    o, clip = _output(s, oid)
    if o.review != "approved":
        raise PostingError("Approve it first")
    if not o.file_path or not Path(o.file_path).exists():
        raise PostingError("The video file is gone (expired or deleted)")
    d = o.destination
    from .media.ffmpeg import probe
    dur = probe(Path(o.file_path)).duration
    return {"output_id": o.id, "clip_id": clip.id, "video_path": str(Path(o.file_path).resolve()), "caption": o.description,
            "title": o.title, "platform": o.platform, "destination": {"id": d.id, "handle": d.handle, "name": d.display_name} if d else None,
            "width": o.width, "height": o.height, "aspect_ratio": f"{o.width}:{o.height}" if o.width else None,
            "duration": round(dur or 0, 2), "scheduled_at": o.scheduled_at.isoformat() if o.scheduled_at else None}


def client(ctx, s: Session) -> Postiz:
    key = (ctx.secrets.get(SECRET) or {}).get("api_key", "")
    return Postiz(load_settings(s).posting.postiz_url, key)


def send(ctx, oid: int, mode: str, actor: str) -> dict:
    """Job: upload the approved video to Postiz on the page's channel. Never sends what isn't approved or is held back."""
    with ctx.db.session() as s:
        o, clip = _output(s, oid)
        why = held_back(clip, load_settings(s).posting.min_virality)
        if o.review != "approved" or why:
            raise PostingError(why or "Not approved")
        iid = ((o.destination.settings or {}) if o.destination else {}).get("postiz_integration_id")
        if not iid:
            raise PostingError(f"Pick this page's Postiz channel first (Destinations > {o.destination.display_name if o.destination else 'page'})")
        api = client(ctx, s)
        video, caption, title, when = Path(o.file_path), o.description, o.title, o.scheduled_at
    if mode == "schedule" and not when:
        raise PostingError("Set a time to schedule it")
    integration = next((i for i in api.integrations() if i["id"] == iid), None)
    if not integration or integration["disabled"]:
        raise PostingError("That Postiz channel isn't connected (or is turned off) in Postiz")
    pid = api.create(integration=integration, video=video, caption=caption, title=title, mode=mode, when=when if mode == "schedule" else None)
    with ctx.db.session() as s:
        o = s.get(ClipOutput, oid)
        o.postiz_post_id, o.postiz_state, o.postiz_error = pid, "draft" if mode == "draft" else "queued", None
        audit(s, "output.sent_to_postiz", "clip_output", oid, {"by": actor, "mode": mode, "post": pid})
        if mode != "draft":
            ctx.jobs.enqueue("postiz.sync", {"output_id": oid}, max_attempts=1, delay=60, session=s)
    return {"post_id": pid, "state": "draft" if mode == "draft" else "queued"}


def sync(ctx, oid: int) -> dict:
    """Job: read the post back from Postiz. Live: its URL goes on the video (and analytics picks it up from there)."""
    with ctx.db.session() as s:
        o = s.get(ClipOutput, oid)
        if not o or not o.postiz_post_id:
            return {"skipped": True}
        api, pid, around = client(ctx, s), o.postiz_post_id, o.scheduled_at or o.created_at
    st = api.status(pid, around)
    with ctx.db.session() as s:
        o = s.get(ClipOutput, oid)
        o.postiz_state, o.postiz_error = st["state"], st["error"]
        if st["state"] == "published":
            o.post_url = st["url"] or o.post_url
            o.status, o.uploaded_at = "uploaded", o.uploaded_at or datetime.now(timezone.utc)
            ctx.jobs.enqueue("campaigns.check", {}, max_attempts=1, session=s)  # it may now qualify for a campaign
        elif st["state"] in ("queued", "unknown") and (datetime.now(timezone.utc) - around.replace(tzinfo=around.tzinfo or timezone.utc)).days < 3:
            ctx.jobs.enqueue("postiz.sync", {"output_id": oid}, max_attempts=1, delay=300, session=s)  # check again later
    return st


def register(ctx) -> None:
    def run(fn):
        def handler(jc, pl):
            try:
                return fn(pl)
            except (PostingError, PostizError) as e:
                with ctx.db.session() as s:
                    o = s.get(ClipOutput, pl["output_id"])
                    if o:
                        o.postiz_state, o.postiz_error = "error", str(e)
                return {"error": str(e)}
        return handler
    ctx.jobs.register("postiz.send", run(lambda pl: send(ctx, pl["output_id"], pl.get("mode", "draft"), pl.get("by", "auto"))))
    ctx.jobs.register("postiz.sync", run(lambda pl: sync(ctx, pl["output_id"])))

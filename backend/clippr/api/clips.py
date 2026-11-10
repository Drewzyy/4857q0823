"""Ready-to-upload clips, the activity feed of source posts, and Discord notifications."""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

import httpx
from fastapi import APIRouter, Depends
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import notify
from ..audit import audit
from ..fetch import VIDEO_LINK, FetchError
from ..media.ffmpeg import probe
from ..media.overlay import Word, apply_text_edit
from ..models import Clip, ClipOutput, Creator, Job, ReferenceVideo, Setting, SourceAccount
from ..schemas import ClipEdit, OverlaySettings, deep_merge, lenient
from .deps import ApiError, ctx, db, get_or_404
from .system import load_settings

router = APIRouter()


def _dt(v):
    return v.isoformat() if v else None


def _output(o: ClipOutput) -> dict:
    d = o.destination
    return {"id": o.id, "platform": o.platform, "title": o.title, "description": o.description, "status": o.status,
            "destination": {"id": d.id, "display_name": d.display_name, "handle": d.handle} if d else None,
            "width": o.width, "height": o.height, "fps": o.fps, "size_bytes": o.size_bytes,
            "available": bool(o.file_path and Path(o.file_path).exists()), "uploaded_at": _dt(o.uploaded_at),
            "video_title": o.video_title, "overlay": lenient(OverlaySettings, o.overlay).model_dump(),
            "render_state": o.render_state, "render_error": o.render_error, "post_url": o.post_url,
            # Changes whenever the file is re-rendered, so the preview reloads.
            "version": Path(o.file_path).name if o.file_path else None}


def _reference(r: ReferenceVideo | None) -> dict | None:
    if not r:
        return None
    return {"id": r.id, "platform": r.platform, "url": r.url, "title": r.title, "thumbnail_url": r.thumbnail_url,
            "posted_at": _dt(r.posted_at), "status": r.status, "status_detail": r.status_detail,
            "source": {"id": r.source.id, "username": r.source.username} if r.source else None,
            "creator": {"id": r.creator.id, "name": r.creator.name, "color": r.creator.color} if r.creator else None,
            "vod_url": r.vod_url, "vod_start": r.vod_start, "vod_end": r.vod_end, "match_confidence": r.match_confidence,
            "views": r.views, "likes": r.likes, "created_at": _dt(r.created_at), "updated_at": _dt(r.updated_at)}


@router.get("/clips")
def list_clips(status: Literal["ready", "uploaded", "expired", "all"] = "ready", s: Session = Depends(db)):
    out = []
    for c in s.scalars(select(Clip).order_by(Clip.created_at.desc()).limit(300)).unique():
        outputs = [_output(o) for o in s.scalars(select(ClipOutput).where(ClipOutput.clip_id == c.id).order_by(ClipOutput.id)).unique()]
        if status != "all" and not any(o["status"] == status for o in outputs):
            continue
        out.append({"id": c.id, "title": c.title, "status": c.status, "created_at": _dt(c.created_at), "expires_at": _dt(c.expires_at),
                    "creator": {"id": c.creator.id, "name": c.creator.name, "color": c.creator.color} if c.creator else None,
                    "vod_url": c.vod_url, "vod_start": c.vod_start, "vod_end": c.vod_end, "stream_date": _dt(c.stream_date),
                    "captions_text": " ".join(w["text"] for w in (c.words or [])), "has_captions": bool(c.words),
                    "captions_note": c.captions_note, "editable": _has_footage(c),
                    "reference": _reference(c.reference), "outputs": outputs})
    return out


class OutputPatch(BaseModel):
    title: str | None = Field(None, max_length=200)
    description: str | None = Field(None, max_length=5000)
    status: Literal["ready", "uploaded"] | None = None


@router.patch("/outputs/{oid}")
def update_output(oid: int, body: OutputPatch, s: Session = Depends(db)):
    o = get_or_404(s, ClipOutput, oid, "Clip")
    if o.status == "expired":
        raise ApiError(409, "expired", "This clip has expired and its video was deleted")
    data = body.model_dump(exclude_none=True)
    for k, v in data.items():
        setattr(o, k, v)
    if data.get("status") == "uploaded":
        o.uploaded_at = datetime.now(timezone.utc)
        audit(s, "clip.marked_uploaded", "output", oid, {"platform": o.platform})
    elif data.get("status") == "ready":
        o.uploaded_at = None
    return _output(o)


def _safe_name(text: str) -> str:
    return (re.sub(r'[<>:"/\\|?*\x00-\x1f]+', "", text).strip(" .") or "clip")[:80]


def _reveal(path: Path) -> None:
    try:
        if sys.platform == "darwin":
            subprocess.Popen(["open", "-R", str(path)])
        elif sys.platform == "win32":
            subprocess.Popen(["explorer", f"/select,{path}"])
    except OSError:
        pass


@router.post("/outputs/{oid}/save")
def save_to_downloads(oid: int, s: Session = Depends(db), c=Depends(ctx)):
    """Copy the full-quality file into Downloads/Vyral and show it in Finder / File Explorer."""
    o = get_or_404(s, ClipOutput, oid, "Clip")
    if not o.file_path or not Path(o.file_path).exists():
        raise ApiError(410, "expired", "This clip's video has expired and was deleted to save space")
    if o.render_state == "rendering":
        raise ApiError(409, "rendering", "This video is being re-rendered with your changes. Try again in a moment.")
    folder = Path(os.environ.get("CLIPPR_DOWNLOADS_DIR") or Path.home() / "Downloads") / "Vyral"
    folder.mkdir(parents=True, exist_ok=True)
    dest_name = o.destination.display_name if o.destination else o.platform
    target = folder / f"{_safe_name(dest_name)} - {_safe_name(o.title)}.mp4"
    n = 2
    while target.exists():
        target = folder / f"{_safe_name(dest_name)} - {_safe_name(o.title)} ({n}).mp4"
        n += 1
    shutil.copyfile(o.file_path, target)
    audit(s, "clip.saved", "output", oid, {"platform": o.platform})
    if c.config.desktop_mode:
        _reveal(target)
    return {"path": str(target)}


@router.get("/media/outputs/{oid}")
def media(oid: int, download: bool = False, s: Session = Depends(db)):
    o = get_or_404(s, ClipOutput, oid, "Clip")
    if not o.file_path or not Path(o.file_path).exists():
        raise ApiError(410, "expired", "This clip's video has expired")
    name = f"{_safe_name(o.destination.display_name if o.destination else o.platform)} - {_safe_name(o.title)}.mp4"
    return FileResponse(o.file_path, media_type="video/mp4", filename=name if download else None,
                        content_disposition_type="attachment" if download else "inline")


class VideoTextIn(BaseModel):
    video_title: str | None = Field(None, max_length=200)
    overlay: dict | None = None
    apply_style_to_all: bool = False  # use this style for every page of this clip


def _has_footage(clip: Clip) -> bool:
    """The downloaded stream section the clip was cut from is deleted when the clip expires."""
    return bool(clip.source_path and Path(clip.source_path).exists())


def _footage(clip: Clip) -> Path:
    if not _has_footage(clip):
        raise ApiError(410, "expired", "The original footage for this clip has expired, so it can't be changed anymore")
    return Path(clip.source_path)


def _footage_seconds(clip: Clip) -> float:
    # The section always covers the matched cut, so that's a safe floor if the file reports no length.
    return probe(_footage(clip)).duration or (clip.source_start or 0.0) + (clip.source_duration or 0.0)


def _live_outputs(s: Session, cid: int) -> list[ClipOutput]:
    return list(s.scalars(select(ClipOutput).where(ClipOutput.clip_id == cid, ClipOutput.status != "expired")).unique())


@router.patch("/outputs/{oid}/video")
def edit_video_text(oid: int, body: VideoTextIn, c=Depends(ctx), s: Session = Depends(db)):
    """Change the title / caption style burned into this video, then re-render it."""
    o = get_or_404(s, ClipOutput, oid, "Clip")
    clip = s.get(Clip, o.clip_id)
    _footage(clip)
    targets = [o]
    if body.overlay is not None:
        try:
            ov = OverlaySettings.model_validate(deep_merge(lenient(OverlaySettings, o.overlay).model_dump(), body.overlay)).model_dump()
        except ValidationError as e:
            first = e.errors()[0]
            raise ApiError(422, "validation", f"{'.'.join(str(x) for x in first['loc'])}: {first['msg']}")
        if body.apply_style_to_all:
            targets = _live_outputs(s, clip.id)
        for t in targets:
            t.overlay = ov
    if body.video_title is not None:
        o.video_title = body.video_title.strip()
    for t in targets:
        t.render_state, t.render_error = "rendering", None
    s.flush()
    c.jobs.enqueue("clip.rerender", {"output_ids": [t.id for t in targets]}, max_attempts=1, session=s)
    return _output(o)


@router.get("/clips/{cid}/editor")
def editor_data(cid: int, s: Session = Depends(db)):
    clip = get_or_404(s, Clip, cid, "Clip")
    start = round(clip.source_start or 0.0, 2)
    try:  # an edit saved by an older version gets defaults for options added since
        edit = ClipEdit.model_validate(clip.edit).model_dump()
    except ValidationError:
        edit = ClipEdit(start=start, end=round(start + (clip.source_duration or 1.0), 2)).model_dump()
    return {"id": clip.id, "title": clip.title, "section_duration": _footage_seconds(clip),
            "original_start": clip.source_start or 0.0, "original_duration": clip.source_duration or 0.0,
            "edit": edit, "words": clip.words or [], "outputs": [_output(o) for o in _live_outputs(s, cid)]}


@router.get("/media/clips/{cid}/source")
def clip_source(cid: int, s: Session = Depends(db)):
    return FileResponse(_footage(get_or_404(s, Clip, cid, "Clip")), media_type="video/mp4")


@router.put("/clips/{cid}/edit")
def save_edit(cid: int, body: ClipEdit, c=Depends(ctx), s: Session = Depends(db)):
    """Save the editor's changes and re-render every page of this clip."""
    clip = get_or_404(s, Clip, cid, "Clip")
    if body.end > _footage_seconds(clip) + 0.05 or body.end - body.start < 1:
        raise ApiError(422, "validation", "The clip must be at least 1 second long and inside the downloaded footage")
    clip.edit = body.model_dump()
    outs = _live_outputs(s, cid)
    for o in outs:
        o.render_state, o.render_error = "rendering", None
    s.flush()
    c.jobs.enqueue("clip.rerender", {"output_ids": [o.id for o in outs]}, max_attempts=1, session=s)
    audit(s, "clip.edited", "clip", cid)
    return {"rendering": len(outs)}


class CaptionsIn(BaseModel):
    text: str = Field(max_length=20000)


@router.patch("/clips/{cid}/captions")
def edit_captions(cid: int, body: CaptionsIn, c=Depends(ctx), s: Session = Depends(db)):
    """Fix wrongly heard words. Timing is kept; every page of this clip is re-rendered."""
    clip = get_or_404(s, Clip, cid, "Clip")
    _footage(clip)
    if not clip.words:
        raise ApiError(409, "no_captions", "This clip has no captions to edit")
    clip.words = [w.to_dict() for w in apply_text_edit([Word.from_dict(w) for w in clip.words], body.text)]
    outs = _live_outputs(s, cid)
    for o in outs:
        o.render_state, o.render_error = "rendering", None
    s.flush()
    c.jobs.enqueue("clip.rerender", {"output_ids": [o.id for o in outs]}, max_attempts=1, session=s)
    return {"captions_text": " ".join(w["text"] for w in clip.words), "rendering": len(outs)}


@router.delete("/clips/{cid}", status_code=204)
def delete_clip(cid: int, s: Session = Depends(db)):
    clip = get_or_404(s, Clip, cid, "Clip")
    for o in s.scalars(select(ClipOutput).where(ClipOutput.clip_id == cid)).unique():
        if o.file_path:
            Path(o.file_path).unlink(missing_ok=True)
    if clip.files_dir:
        shutil.rmtree(clip.files_dir, ignore_errors=True)
    audit(s, "clip.deleted", "clip", cid)
    s.delete(clip)


# ---------------- activity (source posts) ----------------
@router.get("/references")
def list_references(include_baseline: bool = False, limit: int = 100, s: Session = Depends(db)):
    q = select(ReferenceVideo).order_by(ReferenceVideo.created_at.desc()).limit(min(max(limit, 1), 500))
    if not include_baseline:
        q = q.where(ReferenceVideo.status != "baseline")
    return [_reference(r) for r in s.scalars(q).unique()]


class ManualIn(BaseModel):
    url: str = Field(min_length=8, max_length=500)
    source_id: int | None = None
    creator_id: int | None = None


@router.post("/references", status_code=201)
def add_reference(body: ManualIn, c=Depends(ctx), s: Session = Depends(db)):
    if not re.match(r"^https://(www\.|m\.|vm\.|vt\.)?(tiktok\.com|youtube\.com|youtu\.be)/", body.url.strip()):
        raise ApiError(422, "invalid_input", "Paste a TikTok or YouTube Shorts video link")
    if body.creator_id and not s.get(Creator, body.creator_id):
        raise ApiError(422, "validation", "Creator not found")
    if body.source_id and not s.get(SourceAccount, body.source_id):
        raise ApiError(422, "validation", "Source account not found")
    try:
        rid = c.pipeline.add_manual(body.url.strip(), body.source_id, body.creator_id)
    except FetchError as e:
        raise ApiError(502, "fetch_failed", f"Couldn't open that video: {e}")
    return {"id": rid}


class IntakeIn(BaseModel):
    urls: list[str] = Field(min_length=1, max_length=50)
    from_clipboard: bool = False


@router.post("/intake")
def intake(body: IntakeIn, c=Depends(ctx), s: Session = Depends(db)):
    """Video links to clip: copied (the desktop app watches the clipboard) or pasted in a batch."""
    if body.from_clipboard and not load_settings(s).intake.clipboard:
        return {"queued": 0, "ignored": len(body.urls)}
    links = list(dict.fromkeys(u.strip() for u in body.urls if VIDEO_LINK.match(u.strip())))
    for url in links:  # a link Vyral already has (or is making) is skipped when the job runs
        c.jobs.enqueue("intake.link", {"url": url}, max_attempts=3, session=s)
    return {"queued": len(links), "ignored": len(body.urls) - len(links)}


class RetryIn(BaseModel):
    vod_url: str | None = Field(None, max_length=500)


@router.post("/references/{rid}/stop")
def stop_reference(rid: int, c=Depends(ctx), s: Session = Depends(db)):
    """Stop working on a post (e.g. a long search). Retry starts it again."""
    r = get_or_404(s, ReferenceVideo, rid, "Post")
    for job in s.scalars(select(Job).where(Job.kind == "clip.build", Job.status.in_(("queued", "running")))):
        if job.payload.get("reference_id") == rid:
            job.status, job.finished_at = "cancelled", datetime.now(timezone.utc)
    if r.status in ("new", "processing"):
        r.status, r.status_detail = "failed", "Stopped. Press Retry to try again."
    return _reference(r)


@router.post("/references/{rid}/retry")
def retry_reference(rid: int, body: RetryIn, c=Depends(ctx), s: Session = Depends(db)):
    r = get_or_404(s, ReferenceVideo, rid, "Post")
    if r.status == "processing":
        raise ApiError(409, "busy", "Vyral is already working on this one")
    payload: dict = {"reference_id": rid}
    if body.vod_url:
        from ..fetch import is_single_video

        if not is_single_video(body.vod_url):
            raise ApiError(422, "invalid_input", "Paste the link to the specific stream (twitch.tv/videos/… or a YouTube video link)")
        payload["vod_url"] = body.vod_url.strip()
    r.status, r.status_detail = "new", "Queued"
    c.jobs.enqueue("clip.build", payload, max_attempts=3, session=s)
    return _reference(r)


@router.post("/sources/{sid}/check")
def check_now(sid: int, c=Depends(ctx), s: Session = Depends(db)):
    src = get_or_404(s, SourceAccount, sid, "Source account")
    from ..fetch import MONITORABLE

    if src.platform not in MONITORABLE:
        raise ApiError(422, "unsupported", f"Vyral can't watch {src.platform} accounts yet. TikTok and YouTube are supported.")
    c.jobs.enqueue("source.check", {"source_id": sid}, max_attempts=1, session=s)
    return {"queued": True}


# ---------------- notifications ----------------
class NotifyIn(BaseModel):
    webhook_url: str | None = Field(None, max_length=300)
    on_new_post: bool | None = None
    on_clip_ready: bool | None = None
    on_problem: bool | None = None


def _notify_state(s: Session, c) -> dict:
    hook = (c.secrets.get(notify.SECRET_KEY) or {}).get("url")
    return {"configured": bool(hook), "webhook_hint": ("…" + hook[-6:]) if hook else None, **notify.prefs(s)}


@router.get("/notifications")
def get_notifications(s: Session = Depends(db), c=Depends(ctx)):
    return _notify_state(s, c)


@router.put("/notifications")
def put_notifications(body: NotifyIn, s: Session = Depends(db), c=Depends(ctx)):
    if body.webhook_url is not None:
        url = body.webhook_url.strip()
        if not notify.valid_webhook(url):
            raise ApiError(422, "invalid_webhook", "That isn't a Discord webhook link. In Discord: channel settings > Integrations > Webhooks > Copy Webhook URL.")
        c.secrets.set(notify.SECRET_KEY, {"url": url})
        audit(s, "notifications.webhook_set", "settings")
    prefs = {k: v for k, v in body.model_dump(exclude_none=True).items() if k != "webhook_url"}
    if prefs:
        row = s.get(Setting, notify.SETTINGS_KEY)
        merged = {**notify.prefs(s), **prefs}
        if row:
            row.value = merged
        else:
            s.add(Setting(key=notify.SETTINGS_KEY, value=merged))
        s.flush()
    return _notify_state(s, c)


@router.delete("/notifications/webhook", status_code=204)
def delete_webhook(s: Session = Depends(db), c=Depends(ctx)):
    c.secrets.delete(notify.SECRET_KEY)
    audit(s, "notifications.webhook_removed", "settings")


@router.post("/notifications/test")
def test_notification(c=Depends(ctx)):
    hook = (c.secrets.get(notify.SECRET_KEY) or {}).get("url")
    if not hook:
        raise ApiError(409, "not_configured", "Add a Discord webhook first")
    try:
        with httpx.Client(timeout=15) as http:
            notify.send(http, hook, {"content": "👋 Vyral is connected. You'll get pings here when source accounts post and when clips are ready."})
    except notify.NotifyError as e:
        raise ApiError(502, "discord_error", str(e))
    except httpx.HTTPError:
        raise ApiError(502, "network", "Couldn't reach Discord. Check your internet connection.")
    return {"sent": True}

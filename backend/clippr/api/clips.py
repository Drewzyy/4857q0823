"""Ready-to-upload clips, the activity feed of source posts, and Discord notifications."""
from __future__ import annotations

import re
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, BackgroundTasks, Depends
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session, object_session

from .. import dropbox, files
from ..audit import audit
from ..fetch import FetchError, count_links
from ..media.ffmpeg import probe
from ..media.overlay import Word, apply_text_edit
from ..models import Clip, ClipOutput, Creator, Job, ReferenceVideo, SourceAccount
from ..schemas import VIDEO_HEIGHT, ClipEdit, OverlaySettings, deep_merge, lenient
from .deps import ApiError, ctx, db, get_or_404
from .system import load_settings, save_folder

router = APIRouter()


def _dt(v):
    return v.isoformat() if v else None


def _output(o: ClipOutput) -> dict:
    d = o.destination
    return {"id": o.id, "platform": o.platform, "title": o.title, "description": o.description, "status": o.status,
            "destination": {"id": d.id, "display_name": d.display_name, "handle": d.handle} if d else None,
            "width": o.width, "height": o.height, "fps": o.fps, "size_bytes": o.size_bytes,
            "available": bool(o.file_path and Path(o.file_path).exists()),
            "has_thumbnail": bool(o.file_path and Path(o.file_path).with_suffix(".jpg").exists()), "uploaded_at": _dt(o.uploaded_at),
            "video_title": o.video_title, "overlay": lenient(OverlaySettings, o.overlay).model_dump(),
            "render_state": o.render_state, "render_error": o.render_error, "post_url": o.post_url,
            "review": o.review, "review_note": o.review_note, "reviewed_by": o.reviewed_by, "quality": o.quality,
            "dropbox": dropbox.status_for(object_session(o), o.file_path),
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
    q = select(Clip).order_by(Clip.created_at.desc()).limit(300)
    if status != "all":  # filtered in the database, not after loading every clip
        q = q.where(Clip.id.in_(select(ClipOutput.clip_id).where(ClipOutput.status == status)))
    clips = list(s.scalars(q).unique())
    # Every clip's pages in one query (this list is polled while clips are being made).
    by_clip: dict[int, list[ClipOutput]] = {}
    if clips:
        for o in s.scalars(select(ClipOutput).where(ClipOutput.clip_id.in_([c.id for c in clips])).order_by(ClipOutput.id)).unique():
            by_clip.setdefault(o.clip_id, []).append(o)
    for c in clips:
        outputs = [_output(o) for o in by_clip.get(c.id, [])]
        out.append({"id": c.id, "title": c.title, "status": c.status, "created_at": _dt(c.created_at), "expires_at": _dt(c.expires_at),
                    "creator": {"id": c.creator.id, "name": c.creator.name, "color": c.creator.color} if c.creator else None,
                    "vod_url": c.vod_url, "vod_start": c.vod_start, "vod_end": c.vod_end, "stream_date": _dt(c.stream_date),
                    "captions_text": " ".join(w["text"] for w in (c.words or [])), "has_captions": bool(c.words),
                    "captions_note": c.captions_note, "editable": _has_footage(c), "grade": c.grade, "safety": c.safety, "content": c.content,
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
    text = re.sub(r"\s{2,}", " ", re.sub("[\U0001F000-\U0001FAFF\u2600-\u27BF\uFE0F\u200D]+", "", text))  # emoji: unreliable in file names
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
    folder = save_folder(load_settings(s))
    try:
        folder.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        raise ApiError(422, "folder", f"Vyral can't save into {folder}: {e.strerror or e}. Pick another folder in Settings.")
    dest_name = o.destination.display_name if o.destination else o.platform
    target = folder / f"{_safe_name(dest_name)} - {_safe_name(o.title)}.mp4"
    n = 2
    while target.exists():
        target = folder / f"{_safe_name(dest_name)} - {_safe_name(o.title)} ({n}).mp4"
        n += 1
    shutil.copyfile(o.file_path, target)
    if (thumb := Path(o.file_path).with_suffix(".jpg")).exists():
        shutil.copyfile(thumb, target.with_suffix(".jpg"))
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


@router.get("/media/outputs/{oid}/thumbnail")
def media_thumbnail(oid: int, download: bool = False, s: Session = Depends(db)):
    o = get_or_404(s, ClipOutput, oid, "Clip")
    thumb = Path(o.file_path).with_suffix(".jpg") if o.file_path else None
    if not thumb or not thumb.exists():
        raise ApiError(404, "no_thumbnail", "This clip has no thumbnail yet")
    name = f"{_safe_name(o.destination.display_name if o.destination else o.platform)} - {_safe_name(o.title)}.jpg"
    return FileResponse(thumb, media_type="image/jpeg", filename=name if download else None,
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
    return list(s.scalars(select(ClipOutput).where(ClipOutput.clip_id == cid, ClipOutput.status.not_in(("expired", "withdrawn")))).unique())


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
    e = dict(clip.edit or {})
    if e.get("hide_title") and (body.video_title is not None or (body.overlay or {}).get("title")):
        # The user chose this title themselves: it replaces the pre-edit headline on every page of the clip.
        clip.edit = {**e, "hide_title": False, "texts": [t for t in e.get("texts") or [] if not t.get("box")]}
        targets = list({t.id: t for t in [*targets, *_live_outputs(s, clip.id)]}.values())
    for t in targets:
        t.render_state, t.render_error = "rendering", None
    s.flush()
    c.jobs.enqueue("clip.rerender", {"output_ids": [t.id for t in targets]}, max_attempts=1, session=s)
    return _output(o)


@router.get("/clips/{cid}/editor")
def editor_data(cid: int, s: Session = Depends(db)):
    clip = get_or_404(s, Clip, cid, "Clip")
    start = round(clip.source_start or 0.0, 2)
    # Clips from before framing was saved were rendered fit to frame, and stay that way until changed here.
    try:
        edit = ClipEdit.model_validate({"video_height": 0, **clip.edit}).model_dump()
    except ValidationError:
        edit = ClipEdit(start=start, end=round(start + (clip.source_duration or 1.0), 2), video_height=0).model_dump()
    return {"id": clip.id, "title": clip.title, "section_duration": _footage_seconds(clip),
            "original_start": clip.source_start or 0.0, "original_duration": clip.source_duration or 0.0,
            "edit": edit, "default_video_height": VIDEO_HEIGHT, "words": clip.words or [], "grade": clip.grade,
            "creator": {"id": clip.creator.id, "name": clip.creator.name, "facecam": clip.creator.facecam} if clip.creator else None, "outputs": [_output(o) for o in _live_outputs(s, cid)]}


@router.get("/media/clips/{cid}/source")
def clip_source(cid: int, s: Session = Depends(db)):
    return FileResponse(_footage(get_or_404(s, Clip, cid, "Clip")), media_type="video/mp4")


def apply_edit(s: Session, jobs, clip: Clip, body: ClipEdit, by: str = "you") -> int:
    """Save an edit (from the editor or from Muse) and re-render every page of the clip. The transcript is kept,
    so nothing is transcribed again. An approval was for the exact video, so a changed video needs approving again."""
    if body.end > _footage_seconds(clip) + 0.05 or body.end - body.start < 1:
        raise ApiError(422, "validation", "The clip must be at least 1 second long and inside the downloaded footage")
    from ..media.deadair import relative
    kept = body.end - body.start - sum(b - a for a, b in relative(body.cuts, body.start, body.end - body.start))
    if kept < 1:
        raise ApiError(422, "validation", "Your cuts leave less than 1 second of clip")
    clip.edit = body.model_dump()
    outs = _live_outputs(s, clip.id)
    for o in outs:
        o.render_state, o.render_error = "rendering", None
        if o.review == "approved" and not o.post_url:
            o.review = "pending"
    s.flush()
    jobs.enqueue("clip.rerender", {"output_ids": [o.id for o in outs]}, max_attempts=1, session=s)
    audit(s, "clip.edited", "clip", clip.id, {"by": by})
    return len(outs)


@router.put("/clips/{cid}/edit")
def save_edit(cid: int, body: ClipEdit, c=Depends(ctx), s: Session = Depends(db)):
    """Save the editor's changes and re-render every page of this clip."""
    return {"rendering": apply_edit(s, c.jobs, get_or_404(s, Clip, cid, "Clip"), body)}


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


def _remove_clip(s: Session, clip: Clip) -> list[str]:
    """The clip and its page videos from the database; returns its files (videos, thumbnails, footage) to delete
    once that's saved. Copies already in Dropbox stay there."""
    gone = []
    for o in s.scalars(select(ClipOutput).where(ClipOutput.clip_id == clip.id)).unique():
        if o.file_path:
            gone.append(o.file_path)
    if clip.files_dir:
        gone.append(clip.files_dir)
    s.delete(clip)
    return gone


def _delete_files(paths: list[str]) -> None:
    for p in paths:
        files.remove_video(p) if p.endswith(".mp4") else files.remove(p)


@router.delete("/clips/{cid}", status_code=204)
def delete_clip(cid: int, tasks: BackgroundTasks, s: Session = Depends(db)):
    clip = get_or_404(s, Clip, cid, "Clip")
    audit(s, "clip.deleted", "clip", cid)
    tasks.add_task(_delete_files, _remove_clip(s, clip))


CLEAR_PHRASE = "DELETE ALL CLIPS"


class ClearAll(BaseModel):
    confirm: str = Field(max_length=40)


@router.post("/clips/clear-all")
def clear_all_clips(body: ClearAll, tasks: BackgroundTasks, s: Session = Depends(db)):
    """Deletes every clip and its videos from this computer. Sources, pages, campaigns and settings stay, and so do
    copies already in Dropbox. Needs the phrase typed out, so it can't happen by a stray click."""
    if body.confirm != CLEAR_PHRASE:
        raise ApiError(422, "confirm", f'Type {CLEAR_PHRASE} to delete every clip.')
    clips = s.scalars(select(Clip)).unique().all()
    gone = [p for clip in clips for p in _remove_clip(s, clip)]
    tasks.add_task(_delete_files, gone)  # after the database is saved
    for job in s.scalars(select(Job).where(Job.kind.in_(("clip.rerender", "clip.recut")), Job.status == "queued")):
        job.status = "cancelled"  # nothing left for them to work on
    audit(s, "clips.cleared", "clip", "", {"deleted": len(clips)})
    return {"deleted": len(clips)}



def _finished_seconds(outs: list[ClipOutput]) -> float | None:
    """How long the finished clip runs: measured when its page videos were checked, else read from a video."""
    for o in outs:
        d = ((o.quality or {}).get("measures") or {}).get("duration")
        if d:
            return float(d)
    for o in outs:
        if o.file_path and Path(o.file_path).exists():
            try:
                return probe(Path(o.file_path)).duration
            except Exception:
                continue
    return None


@router.post("/clips/clear-short")
def clear_short_clips(tasks: BackgroundTasks, s: Session = Depends(db)):
    """Deletes the clips under the shortest a clip may be now (pipeline.FLOOR). Posted clips stay, for their history,
    and so does any clip whose length can't be read."""
    from ..pipeline import FLOOR
    gone, deleted, posted = [], 0, 0
    for clip in s.scalars(select(Clip)).unique().all():
        outs = list(s.scalars(select(ClipOutput).where(ClipOutput.clip_id == clip.id)).unique())
        secs = _finished_seconds(outs)
        if secs is None or secs >= FLOOR:
            continue
        if any(o.status == "uploaded" or o.post_url for o in outs):
            posted += 1
            continue
        gone += _remove_clip(s, clip)
        deleted += 1
    tasks.add_task(_delete_files, gone)
    audit(s, "clips.cleared_short", "clip", "", {"deleted": deleted, "kept_posted": posted})
    return {"deleted": deleted, "kept_posted": posted, "under": FLOOR}

# ---------------- activity (source posts) ----------------
@router.get("/references")
def list_references(include_baseline: bool = False, limit: int = 100, s: Session = Depends(db)):
    q = select(ReferenceVideo).order_by(ReferenceVideo.created_at.desc()).limit(min(max(limit, 1), 500))
    q = q.where(ReferenceVideo.status != "removed")
    if not include_baseline:
        q = q.where(ReferenceVideo.status != "baseline")
    # Where each waiting clip is in the build line (the heavy work runs a few at a time; the rest wait their turn).
    line = s.scalars(select(Job).where(Job.status == "queued", Job.kind.in_(("clip.build", "clip.rerender", "longform.make")))
                     .order_by(Job.run_after, Job.id)).all()
    place = {j.payload.get("reference_id"): n for n, j in enumerate(line, 1) if j.kind == "clip.build"}
    return [{**_reference(r), "queue_position": place.get(r.id)} for r in s.scalars(q).unique()]


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
    urls: list[str] = Field(default_factory=list, max_length=50)
    text: str | None = Field(None, max_length=20000)  # anything pasted: every video link in it is used
    creator_id: int | None = None
    from_clipboard: bool = False


@router.post("/intake")
def intake(body: IntakeIn, c=Depends(ctx), s: Session = Depends(db)):
    """Video links to clip: copied (the desktop app watches the clipboard) or pasted in a batch."""
    if body.from_clipboard and not load_settings(s).intake.clipboard:
        return {"queued": 0, "ignored": len(body.urls)}
    if body.creator_id and not s.get(Creator, body.creator_id):
        raise ApiError(422, "validation", "Creator not found")
    from ..discord_inbox import parse
    pieces = [*body.urls, body.text or ""]
    creators = [(x.id, x.name, list(x.vod_channels or [])) for x in s.scalars(select(Creator))]
    found: dict[str, int | None] = {}
    for piece in pieces:  # a streamer named next to a link (e.g. "jasontheween") means only their streams are searched
        for link, named in parse(piece, creators):
            found.setdefault(link, body.creator_id or named)
    links = list(found)[:50]
    from ..pipeline import own_post
    mine = [u for u in links if own_post(s, u)]  # your own posts (copied for the post-link box) aren't new clips
    links = [u for u in links if u not in mine]
    for url in links:  # a link Vyral already has (or is making) is skipped when the job runs
        c.jobs.enqueue("intake.link", {"url": url, "creator_id": found[url]}, max_attempts=3, session=s)
    others = sum(count_links(p) for p in pieces) - len(links)
    return {"queued": len(links), "ignored": max(others, 0)}


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


def _requeue(c, s: Session, r: ReferenceVideo, vod_url: str | None = None) -> None:
    if r.external_id.startswith("link:"):  # the link itself couldn't be opened: try opening it again
        r.status, r.status_detail = "new", "Opening the link again"
        c.jobs.enqueue("intake.link", {"url": r.url, "creator_id": r.creator_id}, max_attempts=3, session=s)
        return
    payload: dict = {"reference_id": r.id}
    if r.status == "duplicate":  # the user wants this one even though the moment was already clipped
        payload["allow_duplicate"] = True
    if vod_url:
        payload["vod_url"] = vod_url
    r.status, r.status_detail = "new", "Queued"
    c.jobs.enqueue("clip.build", payload, max_attempts=3, session=s)


RETRYABLE = ("failed", "no_match", "needs_setup", "duplicate")


@router.post("/references/retry-all")
def retry_all(c=Depends(ctx), s: Session = Depends(db)):
    """Try every post again that failed, wasn't found, needed setup or was skipped as a repeat."""
    rows = list(s.scalars(select(ReferenceVideo).where(ReferenceVideo.status.in_(RETRYABLE))))
    for r in rows:
        _requeue(c, s, r)
    return {"retried": len(rows)}


@router.delete("/references/{rid}", status_code=204)
def remove_reference(rid: int, s: Session = Depends(db)):
    """Take a post off Activity. Its clip, if one was made, stays in Ready to Upload."""
    r = get_or_404(s, ReferenceVideo, rid, "Post")
    if r.status in ("new", "processing"):
        raise ApiError(409, "busy", "Stop it first, then remove it")
    r.status = "removed"  # kept hidden so the same post isn't picked up as new again


@router.post("/references/clear")
def clear_references(s: Session = Depends(db)):
    """Take every post that failed or wasn't found off Activity."""
    rows = list(s.scalars(select(ReferenceVideo).where(ReferenceVideo.status.in_(("failed", "no_match")))))
    for r in rows:
        r.status = "removed"
    return {"removed": len(rows)}


@router.post("/references/{rid}/retry")
def retry_reference(rid: int, body: RetryIn, c=Depends(ctx), s: Session = Depends(db)):
    r = get_or_404(s, ReferenceVideo, rid, "Post")
    if r.status == "processing":
        raise ApiError(409, "busy", "Vyral is already working on this one")
    vod = None
    if body.vod_url:
        from ..fetch import is_single_video

        if not is_single_video(body.vod_url):
            raise ApiError(422, "invalid_input", "Paste the link to the specific stream (twitch.tv/videos/… or a YouTube video link)")
        vod = body.vod_url.strip()
    _requeue(c, s, r, vod)
    return _reference(r)


@router.post("/sources/{sid}/check")
def check_now(sid: int, c=Depends(ctx), s: Session = Depends(db)):
    src = get_or_404(s, SourceAccount, sid, "Source account")
    from ..fetch import MONITORABLE

    if src.platform not in MONITORABLE:
        raise ApiError(422, "unsupported", f"Vyral can't watch {src.platform} accounts yet. TikTok, YouTube, Twitch and Kick are supported.")
    c.jobs.enqueue("source.check", {"source_id": sid}, max_attempts=1, session=s)
    return {"queued": True}


# ---------------- notifications ----------------


@router.get("/sounds")
def list_sounds(s: Session = Depends(db)):
    """The sound effects a clip can use: Vyral's own (made on this computer), then the user's from the library."""
    from ..media.sfx import catalog
    from ..models import MediaItem
    mine = [{"name": f"lib:{m.id}", "label": m.name, "use": "your sound", "seconds": m.duration or 0, "mine": True}
            for m in s.scalars(select(MediaItem).where(MediaItem.kind == "audio").order_by(MediaItem.name)) if Path(m.path).exists()]
    return [{**x, "mine": False} for x in catalog()] + mine


@router.get("/media/sounds/{name}")  # under /media: the page's audio player passes the token in the URL
def sound_file(name: str, c=Depends(ctx)):
    from ..media import sfx
    if name not in sfx.SOUNDS:
        raise ApiError(404, "not_found", "No sound by that name")
    return FileResponse(sfx.path(name, c.pipeline._dir("sfx")), media_type="audio/wav")


class StreamerIn(BaseModel):
    creator_id: int


@router.post("/clips/{cid}/streamer")
def set_streamer(cid: int, body: StreamerIn, c=Depends(ctx), s: Session = Depends(db)):
    """Vyral picked the wrong streamer for this clip: move it to the right one (its pages, captions and title follow)."""
    get_or_404(s, Clip, cid, "Clip")
    get_or_404(s, Creator, body.creator_id, "Streamer")
    s.commit()
    return c.pipeline.reassign(cid, body.creator_id)

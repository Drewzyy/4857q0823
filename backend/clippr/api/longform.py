"""Long-form: paste a long video's link or drop in a file, and Vyral makes the best moments into clips."""
from __future__ import annotations

import re
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Clip, Creator, Job, LongformVideo
from .deps import ApiError, ctx, db, get_or_404

router = APIRouter()

VIDEO_EXT = {".mp4", ".mov", ".m4v", ".mkv", ".webm", ".avi", ".flv", ".ts"}
MAX_BYTES = 20 * 1024**3


def _out(v: LongformVideo, s: Session) -> dict:
    clips = {c.id: c for c in s.scalars(select(Clip).where(Clip.longform_id == v.id))}
    return {"id": v.id, "url": v.url, "is_file": bool(v.file_path), "title": v.title or (Path(v.file_path).stem if v.file_path else v.url or ""),
            "creator": {"id": v.creator.id, "name": v.creator.name} if v.creator else None, "clips_wanted": v.clips_wanted,
            "status": v.status, "status_detail": v.status_detail, "duration": v.duration, "created_at": v.created_at.isoformat(),
            "moments": [{**m, "clip_title": clips[m["clip_id"]].title if m.get("clip_id") in clips else None} for m in v.moments or []]}


def _queue(c, s: Session, v: LongformVideo) -> None:
    v.status, v.status_detail, v.moments = "new", "Waiting for its turn", []
    c.jobs.enqueue("longform.make", {"longform_id": v.id}, max_attempts=2, session=s)


def _check_creator(s: Session, creator_id: int | None) -> None:
    if creator_id and not s.get(Creator, creator_id):
        raise ApiError(422, "validation", "Streamer not found")


class LinkIn(BaseModel):
    url: str = Field(min_length=8, max_length=500)
    creator_id: int | None = None
    clips_wanted: int = Field(6, ge=1, le=20)


@router.get("/longform")
def list_longform(s: Session = Depends(db)):
    return [_out(v, s) for v in s.scalars(select(LongformVideo).order_by(LongformVideo.created_at.desc()))]


@router.post("/longform", status_code=201)
def add_link(body: LinkIn, c=Depends(ctx), s: Session = Depends(db)):
    url = body.url.strip()
    if not re.match(r"^https?://[\w.-]+\.[a-z]{2,}/\S+$", url, re.I):
        raise ApiError(422, "invalid_input", "Paste the link to one video, like a YouTube video or a Twitch or Kick past broadcast")
    _check_creator(s, body.creator_id)
    v = LongformVideo(url=url, creator_id=body.creator_id, clips_wanted=body.clips_wanted)
    s.add(v)
    s.flush()
    _queue(c, s, v)
    return _out(v, s)


@router.post("/longform/upload", status_code=201)
async def add_file(file: UploadFile = File(...), creator_id: int | None = Form(None), clips_wanted: int = Form(6),
                   c=Depends(ctx), s: Session = Depends(db)):
    """The file is copied into Vyral's data folder and deleted with the long-form entry."""
    ext = Path(file.filename or "").suffix.lower()
    if ext not in VIDEO_EXT:
        raise ApiError(422, "unsupported", "Drop in a video file (MP4, MOV, MKV, WebM)")
    if not 1 <= clips_wanted <= 20:
        raise ApiError(422, "validation", "Ask for 1 to 20 clips")
    _check_creator(s, creator_id)
    folder = c.config.media_dir / "longform"
    folder.mkdir(parents=True, exist_ok=True)
    dest = folder / f"{uuid.uuid4().hex}{ext}"
    size = 0
    with dest.open("wb") as f:
        while chunk := await file.read(4 << 20):
            size += len(chunk)
            if size > MAX_BYTES:
                f.close()
                dest.unlink(missing_ok=True)
                raise ApiError(413, "too_large", "Long-form files are limited to 20 GB")
            f.write(chunk)
    v = LongformVideo(file_path=str(dest), title=Path(file.filename or "video").stem[:300], creator_id=creator_id, clips_wanted=clips_wanted)
    s.add(v)
    s.flush()
    _queue(c, s, v)
    return _out(v, s)


@router.post("/longform/{lid}/retry")
def retry(lid: int, c=Depends(ctx), s: Session = Depends(db)):
    v = get_or_404(s, LongformVideo, lid, "Long-form video")
    if v.status in ("new", "processing"):
        raise ApiError(409, "busy", "Vyral is already working on this one")
    if v.file_path and not Path(v.file_path).exists():
        raise ApiError(410, "missing", "The file is gone from Vyral's data folder. Drop it in again.")
    _queue(c, s, v)
    return _out(v, s)


@router.delete("/longform/{lid}", status_code=204)
def remove(lid: int, s: Session = Depends(db)):
    """Removes the entry (and a dropped-in file). Clips already made stay in Ready to Upload."""
    v = get_or_404(s, LongformVideo, lid, "Long-form video")
    for job in s.scalars(select(Job).where(Job.kind == "longform.make", Job.status.in_(("queued", "running")))):
        if job.payload.get("longform_id") == lid:
            job.status = "cancelled"
    if v.file_path:
        Path(v.file_path).unlink(missing_ok=True)
    s.delete(v)

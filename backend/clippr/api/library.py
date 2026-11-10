"""The media library (gameplay for split screen, animations, stickers) and editor presets built from it."""
from __future__ import annotations

import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..media.ffmpeg import FFmpegError, probe
from ..models import MediaItem, Preset
from ..schemas import PresetData
from .deps import ApiError, ctx, db, get_or_404

router = APIRouter()

VIDEO = {".mp4", ".mov", ".m4v", ".webm", ".mkv"}
IMAGE = {".png", ".jpg", ".jpeg", ".gif", ".webp"}
MAX_BYTES = 2 * 1024**3
TYPES = {".mp4": "video/mp4", ".m4v": "video/mp4", ".mov": "video/quicktime", ".webm": "video/webm", ".mkv": "video/x-matroska",
         ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".gif": "image/gif", ".webp": "image/webp"}


def _item(m: MediaItem) -> dict:
    return {"id": m.id, "name": m.name, "kind": m.kind, "width": m.width, "height": m.height, "duration": m.duration,
            "available": Path(m.path).exists()}


@router.get("/library")
def list_library(s: Session = Depends(db)):
    return [_item(m) for m in s.scalars(select(MediaItem).order_by(MediaItem.created_at.desc()))]


@router.post("/library", status_code=201)
async def add_to_library(file: UploadFile = File(...), c=Depends(ctx), s: Session = Depends(db)):
    """Copies the file into Vyral's library, so it keeps working if the original moves."""
    ext = Path(file.filename or "").suffix.lower()
    if ext not in VIDEO | IMAGE:
        raise ApiError(422, "unsupported", "Add a video (MP4, MOV, WebM) or a picture (PNG, JPG, GIF, WebP)")
    folder = c.config.media_dir / "library"
    folder.mkdir(parents=True, exist_ok=True)
    dest = folder / f"{uuid.uuid4().hex}{ext}"
    size = 0
    with dest.open("wb") as f:
        while chunk := await file.read(1 << 20):
            size += len(chunk)
            if size > MAX_BYTES:
                f.close()
                dest.unlink(missing_ok=True)
                raise ApiError(413, "too_large", "Library files are limited to 2 GB")
            f.write(chunk)
    try:
        info = probe(dest)
    except FFmpegError:
        dest.unlink(missing_ok=True)
        raise ApiError(422, "unreadable", "That file couldn't be read as a video or picture")
    m = MediaItem(name=(Path(file.filename or "file").stem or "file")[:200], kind="video" if ext in VIDEO and ext != ".gif" else "image",
                  path=str(dest), width=info.width, height=info.height, duration=info.duration if ext in VIDEO else None)
    s.add(m)
    s.flush()
    return _item(m)


@router.get("/media/library/{mid}")
def library_file(mid: int, s: Session = Depends(db)):
    m = get_or_404(s, MediaItem, mid, "Library item")
    if not Path(m.path).exists():
        raise ApiError(410, "missing", "This file is no longer in the library folder")
    return FileResponse(m.path, media_type=TYPES.get(Path(m.path).suffix.lower(), "application/octet-stream"))


@router.delete("/library/{mid}", status_code=204)
def remove_from_library(mid: int, s: Session = Depends(db)):
    """Clips already rendered keep it; new renders and presets skip it."""
    m = get_or_404(s, MediaItem, mid, "Library item")
    Path(m.path).unlink(missing_ok=True)
    s.delete(m)


class PresetIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    data: dict = Field(default_factory=dict)


def _preset(p: Preset) -> dict:
    return {"id": p.id, "name": p.name, "data": PresetData.model_validate(p.data or {}).model_dump()}


def _validated(data: dict) -> dict:
    try:
        return PresetData.model_validate(data).model_dump()
    except ValidationError as e:
        first = e.errors()[0]
        raise ApiError(422, "validation", f"{'.'.join(str(x) for x in first['loc'])}: {first['msg']}")


@router.get("/presets")
def list_presets(s: Session = Depends(db)):
    return [_preset(p) for p in s.scalars(select(Preset).order_by(Preset.name))]


@router.post("/presets", status_code=201)
def add_preset(body: PresetIn, s: Session = Depends(db)):
    p = Preset(name=body.name.strip(), data=_validated(body.data))
    s.add(p)
    s.flush()
    return _preset(p)


@router.put("/presets/{pid}")
def update_preset(pid: int, body: PresetIn, s: Session = Depends(db)):
    p = get_or_404(s, Preset, pid, "Preset")
    p.name, p.data = body.name.strip(), _validated(body.data)
    return _preset(p)


@router.delete("/presets/{pid}", status_code=204)
def remove_preset(pid: int, s: Session = Depends(db)):
    s.delete(get_or_404(s, Preset, pid, "Preset"))

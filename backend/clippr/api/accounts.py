"""Creators, folders, source accounts and destination accounts."""
from __future__ import annotations

import csv
import io
import re
import uuid
from typing import Literal

from fastapi import APIRouter, Depends, File, UploadFile
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .. import serialize as ser
from ..audit import audit
from ..models import Creator, DestinationAccount, Folder, FunnelRoute, ReferenceVideo, SourceAccount
from ..platforms import DESTINATION_PLATFORMS
from ..platforms.urls import SUPPORTED_SOURCE_PLATFORMS, SourceInputError, parse_source_input
from ..schemas import DestinationSettings, default_destination_settings
from .deps import ApiError, ctx, db, get_or_404

router = APIRouter()
MAX_IMPORT_BYTES = 1_000_000
MAX_IMPORT_ROWS = 2000
HEX = r"^#[0-9a-fA-F]{6}$"


# ---------------- creators ----------------
class CreatorIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    color: str = Field("#8b5cf6", pattern=HEX)
    notes: str = Field("", max_length=2000)
    vod_channels: list[str] = Field(default_factory=list, max_length=10)
    clip_permission: bool = False


class CreatorPatch(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=120)
    color: str | None = Field(None, pattern=HEX)
    notes: str | None = Field(None, max_length=2000)
    vod_channels: list[str] | None = Field(None, max_length=10)
    clip_permission: bool | None = None


def _clean_channels(links: list[str]) -> list[str]:
    from ..fetch import FetchError, validate_stream_link

    out = []
    for link in links:
        if not link.strip():
            continue
        try:
            v = validate_stream_link(link)
        except FetchError as e:
            raise ApiError(422, "invalid_input", f"{link.strip()[:80]}: {e}")
        if v not in out:
            out.append(v)
    return out


def _creator_counts(s: Session) -> dict[int, dict[str, int]]:
    out: dict[int, dict[str, int]] = {}
    for cid, n in s.execute(select(SourceAccount.creator_id, func.count()).group_by(SourceAccount.creator_id)):
        if cid:
            out.setdefault(cid, {"sources": 0, "destinations": 0})["sources"] = n
    for cid, n in s.execute(select(DestinationAccount.creator_id, func.count()).group_by(DestinationAccount.creator_id)):
        if cid:
            out.setdefault(cid, {"sources": 0, "destinations": 0})["destinations"] = n
    return out


@router.get("/creators")
def list_creators(s: Session = Depends(db)):
    counts = _creator_counts(s)
    return [{**ser.creator(c), **counts.get(c.id, {"sources": 0, "destinations": 0})} for c in s.scalars(select(Creator).order_by(Creator.name))]


def _get_or_create_creator(s: Session, name: str) -> Creator:
    name = name.strip()
    c = s.scalar(select(Creator).where(func.lower(Creator.name) == name.lower()))
    if not c:
        c = Creator(name=name)
        s.add(c)
        s.flush()
    return c


@router.post("/creators", status_code=201)
def create_creator(body: CreatorIn, s: Session = Depends(db)):
    if s.scalar(select(Creator).where(func.lower(Creator.name) == body.name.strip().lower())):
        raise ApiError(409, "duplicate", f"A creator named '{body.name}' already exists")
    c = Creator(name=body.name.strip(), color=body.color, notes=body.notes,
                vod_channels=_clean_channels(body.vod_channels), clip_permission=body.clip_permission)
    s.add(c)
    s.flush()
    audit(s, "creator.created", "creator", c.id, {"name": c.name})
    return ser.creator(c)


@router.patch("/creators/{cid}")
def update_creator(cid: int, body: CreatorPatch, s: Session = Depends(db)):
    c = get_or_404(s, Creator, cid, "Creator")
    data = body.model_dump(exclude_none=True)
    if "vod_channels" in data:
        data["vod_channels"] = _clean_channels(data["vod_channels"])
    for k, v in data.items():
        setattr(c, k, v.strip() if k == "name" else v)
    try:
        s.flush()
    except IntegrityError:
        raise ApiError(409, "duplicate", "Another creator already has that name")
    return ser.creator(c)


@router.delete("/creators/{cid}", status_code=204)
def delete_creator(cid: int, s: Session = Depends(db)):
    c = get_or_404(s, Creator, cid, "Creator")
    audit(s, "creator.deleted", "creator", cid, {"name": c.name})
    s.delete(c)


# ---------------- folders ----------------
class FolderIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)


@router.get("/folders")
def list_folders(s: Session = Depends(db)):
    counts = dict(s.execute(select(SourceAccount.folder_id, func.count()).group_by(SourceAccount.folder_id)).all())
    return [{**ser.folder(f), "sources": counts.get(f.id, 0)} for f in s.scalars(select(Folder).order_by(Folder.name))]


@router.post("/folders", status_code=201)
def create_folder(body: FolderIn, s: Session = Depends(db)):
    if s.scalar(select(Folder).where(func.lower(Folder.name) == body.name.strip().lower())):
        raise ApiError(409, "duplicate", f"A folder named '{body.name}' already exists")
    f = Folder(name=body.name.strip())
    s.add(f)
    s.flush()
    return ser.folder(f)


@router.patch("/folders/{fid}")
def rename_folder(fid: int, body: FolderIn, s: Session = Depends(db)):
    f = get_or_404(s, Folder, fid, "Folder")
    f.name = body.name.strip()
    try:
        s.flush()
    except IntegrityError:
        raise ApiError(409, "duplicate", "Another folder already has that name")
    return ser.folder(f)


@router.delete("/folders/{fid}", status_code=204)
def delete_folder(fid: int, s: Session = Depends(db)):
    s.delete(get_or_404(s, Folder, fid, "Folder"))


# ---------------- source accounts ----------------
def _route_counts(s: Session, col) -> dict[int, int]:
    return dict(s.execute(select(col, func.count()).group_by(col)).all())


class SourceIn(BaseModel):
    input: str = Field(min_length=1, max_length=300, description="username, @username or profile URL")
    platform: Literal["tiktok", "youtube", "twitch", "instagram"] = "tiktok"
    creator_id: int | None = None
    folder_id: int | None = None
    notes: str = Field("", max_length=2000)


class SourcePatch(BaseModel):
    creator_id: int | None = None
    folder_id: int | None = None
    monitoring: Literal["active", "paused"] | None = None
    display_name: str | None = Field(None, max_length=200)
    notes: str | None = Field(None, max_length=2000)


@router.get("/sources")
def list_sources(q: str = "", creator_id: int | None = None, folder_id: int | None = None,
                 monitoring: Literal["active", "paused"] | None = None, platform: str | None = None,
                 s: Session = Depends(db)):
    stmt = select(SourceAccount).order_by(SourceAccount.created_at.desc())
    if q:
        like = f"%{q.strip().lower()}%"
        stmt = stmt.where(or_(func.lower(SourceAccount.username).like(like), func.lower(SourceAccount.display_name).like(like)))
    if creator_id is not None:
        stmt = stmt.where(SourceAccount.creator_id == (creator_id or None)) if creator_id else stmt.where(SourceAccount.creator_id.is_(None))
    if folder_id is not None:
        stmt = stmt.where(SourceAccount.folder_id == folder_id) if folder_id else stmt.where(SourceAccount.folder_id.is_(None))
    if monitoring:
        stmt = stmt.where(SourceAccount.monitoring == monitoring)
    if platform:
        stmt = stmt.where(SourceAccount.platform == platform)
    counts = _route_counts(s, FunnelRoute.source_id)
    seen = dict(s.execute(select(ReferenceVideo.source_id, func.count()).group_by(ReferenceVideo.source_id)).all())
    clipped = dict(s.execute(select(ReferenceVideo.source_id, func.count()).where(ReferenceVideo.status == "ready").group_by(ReferenceVideo.source_id)).all())
    out = []
    for x in s.scalars(stmt).unique():
        d = ser.source(x, counts.get(x.id, 0))
        if x.baseline_done:
            d["videos_discovered"], d["videos_analyzed"] = seen.get(x.id, 0), clipped.get(x.id, 0)
        out.append(d)
    return out


def _check_refs(s: Session, creator_id: int | None, folder_id: int | None) -> None:
    if creator_id and not s.get(Creator, creator_id):
        raise ApiError(422, "validation", "Creator not found")
    if folder_id and not s.get(Folder, folder_id):
        raise ApiError(422, "validation", "Folder not found")


@router.post("/sources", status_code=201)
def add_source(body: SourceIn, s: Session = Depends(db)):
    try:
        parsed = parse_source_input(body.input, body.platform)
    except SourceInputError as e:
        raise ApiError(422, "invalid_input", str(e))
    _check_refs(s, body.creator_id, body.folder_id)
    if s.scalar(select(SourceAccount).where(SourceAccount.platform == parsed.platform, SourceAccount.username == parsed.username)):
        raise ApiError(409, "duplicate", f"@{parsed.username} on {parsed.platform} is already in your sources")
    src = SourceAccount(platform=parsed.platform, username=parsed.username, profile_url=parsed.profile_url,
                        creator_id=body.creator_id, folder_id=body.folder_id, notes=body.notes)
    s.add(src)
    s.flush()
    s.refresh(src)
    audit(s, "source.added", "source", src.id, {"platform": src.platform, "username": src.username})
    return ser.source(src)


@router.post("/sources/import")
async def import_sources(file: UploadFile = File(...), s: Session = Depends(db)):
    """CSV (columns: username or url, creator, folder, platform) or one handle/URL per line."""
    raw = await file.read(MAX_IMPORT_BYTES + 1)
    if len(raw) > MAX_IMPORT_BYTES:
        raise ApiError(413, "too_large", "Import files are limited to 1 MB")
    try:
        content = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        raise ApiError(422, "invalid_input", "The file must be UTF-8 text (CSV)")
    return _import_rows(s, content)


class ImportText(BaseModel):
    text: str = Field(max_length=MAX_IMPORT_BYTES)
    platform: Literal["tiktok", "youtube", "twitch", "instagram"] = "tiktok"
    creator_id: int | None = None
    folder_id: int | None = None


@router.post("/sources/import-text")
def import_sources_text(body: ImportText, s: Session = Depends(db)):
    _check_refs(s, body.creator_id, body.folder_id)
    return _import_rows(s, body.text, body.platform, body.creator_id, body.folder_id)


def _import_rows(s: Session, content: str, default_platform: str = "tiktok", creator_id: int | None = None, folder_id: int | None = None):
    lines = [ln for ln in content.splitlines() if ln.strip()]
    if not lines:
        raise ApiError(422, "invalid_input", "Nothing to import")
    header = [h.strip().lower() for h in next(csv.reader([lines[0]]))]
    is_csv = any(h in ("username", "url", "profile_url", "handle") for h in header)
    rows: list[dict[str, str]] = []
    if is_csv:
        for r in csv.DictReader(io.StringIO("\n".join(lines))):
            rows.append({(k or "").strip().lower(): (v or "").strip() for k, v in r.items()})
    else:
        rows = [{"username": ln.strip()} for ln in lines]
    if len(rows) > MAX_IMPORT_ROWS:
        raise ApiError(413, "too_large", f"Imports are limited to {MAX_IMPORT_ROWS} rows at a time")
    added, skipped, errors = [], 0, []
    seen: set[tuple[str, str]] = set()
    for i, r in enumerate(rows, start=2 if is_csv else 1):
        value = r.get("url") or r.get("profile_url") or r.get("username") or r.get("handle") or ""
        platform = (r.get("platform") or default_platform).lower()
        if platform not in SUPPORTED_SOURCE_PLATFORMS:
            errors.append({"line": i, "input": value, "message": f"Unsupported platform '{platform}'"})
            continue
        try:
            p = parse_source_input(value, platform)
        except SourceInputError as e:
            errors.append({"line": i, "input": value, "message": str(e)})
            continue
        if (p.platform, p.username) in seen or s.scalar(select(SourceAccount.id).where(SourceAccount.platform == p.platform, SourceAccount.username == p.username)):
            skipped += 1
            continue
        seen.add((p.platform, p.username))
        cid = _get_or_create_creator(s, r["creator"]).id if r.get("creator") else creator_id
        fid = folder_id
        if r.get("folder"):
            f = s.scalar(select(Folder).where(func.lower(Folder.name) == r["folder"].lower()))
            if not f:
                f = Folder(name=r["folder"])
                s.add(f)
                s.flush()
            fid = f.id
        src = SourceAccount(platform=p.platform, username=p.username, profile_url=p.profile_url, creator_id=cid, folder_id=fid)
        s.add(src)
        added.append(p.username)
    s.flush()
    audit(s, "source.imported", "source", "", {"added": len(added), "skipped": skipped, "errors": len(errors)})
    return {"added": len(added), "skipped_duplicates": skipped, "errors": errors[:100]}


@router.patch("/sources/{sid}")
def update_source(sid: int, body: SourcePatch, s: Session = Depends(db)):
    src = get_or_404(s, SourceAccount, sid, "Source account")
    data = body.model_dump(exclude_unset=True)
    _check_refs(s, data.get("creator_id"), data.get("folder_id"))
    for k, v in data.items():
        setattr(src, k, v)
    s.flush()
    s.refresh(src)
    if "monitoring" in data:
        audit(s, f"source.{'resumed' if src.monitoring == 'active' else 'paused'}", "source", sid)
    return ser.source(src, _route_counts(s, FunnelRoute.source_id).get(sid, 0))


class BulkSource(BaseModel):
    ids: list[int] = Field(min_length=1, max_length=2000)
    action: Literal["pause", "resume", "delete", "assign"]
    creator_id: int | None = None
    folder_id: int | None = None


@router.post("/sources/bulk")
def bulk_sources(body: BulkSource, s: Session = Depends(db)):
    _check_refs(s, body.creator_id, body.folder_id)
    n = 0
    for src in s.scalars(select(SourceAccount).where(SourceAccount.id.in_(body.ids))).unique():
        n += 1
        if body.action == "delete":
            s.delete(src)
        elif body.action in ("pause", "resume"):
            src.monitoring = "paused" if body.action == "pause" else "active"
        else:
            src.creator_id, src.folder_id = body.creator_id, body.folder_id
    audit(s, f"source.bulk_{body.action}", "source", "", {"count": n})
    return {"updated": n}


@router.delete("/sources/{sid}", status_code=204)
def delete_source(sid: int, s: Session = Depends(db)):
    src = get_or_404(s, SourceAccount, sid, "Source account")
    audit(s, "source.removed", "source", sid, {"username": src.username})
    s.delete(src)


# ---------------- destination accounts ----------------
class DestinationDraftIn(BaseModel):
    platform: Literal["tiktok", "instagram", "youtube", "facebook"]
    display_name: str = Field(min_length=1, max_length=200)
    handle: str = Field("", max_length=100)
    creator_id: int | None = None


class DestinationPatch(BaseModel):
    display_name: str | None = Field(None, min_length=1, max_length=200)
    handle: str | None = Field(None, max_length=100)
    creator_id: int | None = None
    enabled: bool | None = None
    settings: dict | None = None


def _handle(h: str) -> str:
    h = h.strip()
    m = re.search(r"(?:tiktok\.com/|instagram\.com/|youtube\.com/|facebook\.com/)(@?[\w.\-]+)", h)
    if m:
        h = m.group(1)
    h = h.lstrip("@").strip("/")
    if h and not re.fullmatch(r"[\w.\-]{1,60}", h):
        raise ApiError(422, "invalid_input", "Handles can only contain letters, numbers, dots, dashes and underscores")
    return f"@{h}" if h else ""


@router.get("/destinations")
def list_destinations(platform: str | None = None, creator_id: int | None = None, s: Session = Depends(db)):
    stmt = select(DestinationAccount).order_by(DestinationAccount.platform, DestinationAccount.display_name)
    if platform:
        stmt = stmt.where(DestinationAccount.platform == platform)
    if creator_id:
        stmt = stmt.where(DestinationAccount.creator_id == creator_id)
    counts = _route_counts(s, FunnelRoute.destination_id)
    return [ser.destination(d, counts.get(d.id, 0)) for d in s.scalars(stmt).unique()]


@router.post("/destinations", status_code=201)
def add_destination_draft(body: DestinationDraftIn, s: Session = Depends(db)):
    """Add a page you post to. You upload to it yourself, so no login is needed."""
    if body.platform not in DESTINATION_PLATFORMS:
        raise ApiError(422, "validation", "Unsupported platform")
    _check_refs(s, body.creator_id, None)
    d = DestinationAccount(platform=body.platform, external_id=f"manual:{uuid.uuid4().hex}", display_name=body.display_name.strip(),
                           handle=_handle(body.handle), creator_id=body.creator_id, settings=default_destination_settings(body.platform))
    s.add(d)
    s.flush()
    s.refresh(d)
    audit(s, "destination.created", "destination", d.id, {"platform": d.platform})
    return ser.destination(d)


@router.patch("/destinations/{did}")
def update_destination(did: int, body: DestinationPatch, s: Session = Depends(db)):
    d = get_or_404(s, DestinationAccount, did, "Destination account")
    data = body.model_dump(exclude_unset=True)
    _check_refs(s, data.get("creator_id"), None)
    if "settings" in data:
        try:
            merged = {**(d.settings or {}), **(data.pop("settings") or {})}
            d.settings = DestinationSettings.model_validate(merged).model_dump()
        except ValidationError as e:
            first = e.errors()[0]
            raise ApiError(422, "validation", f"{'.'.join(str(x) for x in first['loc'])}: {first['msg']}")
    if "handle" in data:
        data["handle"] = _handle(data["handle"])
    if "display_name" in data:
        data["display_name"] = data["display_name"].strip()
    for k, v in data.items():
        setattr(d, k, v)
    s.flush()
    s.refresh(d)
    audit(s, "destination.updated", "destination", did, {"fields": list(body.model_dump(exclude_unset=True).keys())})
    return ser.destination(d, _route_counts(s, FunnelRoute.destination_id).get(did, 0))


@router.delete("/destinations/{did}", status_code=204)
def delete_destination(did: int, s: Session = Depends(db), c=Depends(ctx)):
    d = get_or_404(s, DestinationAccount, did, "Destination account")
    c.secrets.delete(f"account:{d.platform}:{d.external_id}")
    audit(s, "destination.removed", "destination", did, {"platform": d.platform, "name": d.display_name})
    s.delete(d)

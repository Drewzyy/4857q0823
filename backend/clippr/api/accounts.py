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
from ..models import Creator, DestinationAccount, Folder, ReferenceVideo, SourceAccount
from ..platforms import DESTINATION_PLATFORMS
from ..platforms.urls import SUPPORTED_SOURCE_PLATFORMS, SourceInputError, parse_source_input
from ..schemas import DestinationSettings, deep_merge, default_destination_settings
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
    from ..routing import source_creator_ids

    for src in s.scalars(select(SourceAccount)).unique():
        for cid in source_creator_ids(src):
            out.setdefault(cid, {"sources": 0, "destinations": 0})["sources"] += 1
    from ..routing import destination_creator_ids
    for d in s.scalars(select(DestinationAccount)).unique():
        for cid in destination_creator_ids(d):
            out.setdefault(cid, {"sources": 0, "destinations": 0})["destinations"] += 1
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


class FacecamIn(BaseModel):
    cam: list[float] | None = Field(None, min_length=4, max_length=4)


@router.put("/creators/{cid}/facecam")
def set_creator_facecam(cid: int, body: FacecamIn, s: Session = Depends(db)):
    """Where this streamer's facecam sits. New clips of them use the stacked layout with it; None turns that off."""
    c = get_or_404(s, Creator, cid, "Creator")
    if body.cam:
        x, y, w, h = body.cam
        if not (0 <= x < 1 and 0 <= y < 1 and 0.02 <= w <= 1 and 0.02 <= h <= 1 and x + w <= 1.001 and y + h <= 1.001):
            raise ApiError(422, "validation", "The facecam box has to be inside the frame")
    c.facecam = [round(v, 4) for v in body.cam] if body.cam else None
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
def _page_count(s: Session, src: SourceAccount, pages: list[DestinationAccount] | None = None) -> int:
    """How many enabled pages this account's clips go to."""
    from ..routing import source_creator_ids, takes

    ids = set(source_creator_ids(src))
    pages = pages if pages is not None else list(s.scalars(select(DestinationAccount).where(DestinationAccount.enabled.is_(True))).unique())
    return sum(1 for d in pages if not ids or takes(d, ids))


class SourceIn(BaseModel):
    input: str = Field(min_length=1, max_length=300, description="username, @username or profile URL")
    platform: Literal["tiktok", "youtube", "twitch", "instagram"] = "tiktok"
    creator_id: int | None = None
    creator_ids: list[int] | None = Field(None, max_length=50)
    folder_id: int | None = None
    notes: str = Field("", max_length=2000)


class SourcePatch(BaseModel):
    creator_id: int | None = None
    creator_ids: list[int] | None = Field(None, max_length=50)
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
    want_creator = creator_id
    if folder_id is not None:
        stmt = stmt.where(SourceAccount.folder_id == folder_id) if folder_id else stmt.where(SourceAccount.folder_id.is_(None))
    if monitoring:
        stmt = stmt.where(SourceAccount.monitoring == monitoring)
    if platform:
        stmt = stmt.where(SourceAccount.platform == platform)
    pages = list(s.scalars(select(DestinationAccount).where(DestinationAccount.enabled.is_(True))).unique())
    seen = dict(s.execute(select(ReferenceVideo.source_id, func.count()).group_by(ReferenceVideo.source_id)).all())
    clipped = dict(s.execute(select(ReferenceVideo.source_id, func.count()).where(ReferenceVideo.status == "ready").group_by(ReferenceVideo.source_id)).all())
    from ..routing import source_creator_ids

    by_id = {c.id: c for c in s.scalars(select(Creator))}
    out = []
    for x in s.scalars(stmt).unique():
        ids = source_creator_ids(x)
        if want_creator is not None and ((want_creator and want_creator not in ids) or (not want_creator and ids)):
            continue
        d = ser.source(x, _page_count(s, x, pages), by_id)
        if x.baseline_done:
            d["videos_discovered"], d["videos_analyzed"] = seen.get(x.id, 0), clipped.get(x.id, 0)
        out.append(d)
    return out


def _set_creators(src: SourceAccount, ids: list[int] | None) -> None:
    ids = list(dict.fromkeys(int(i) for i in (ids or [])))
    src.creator_ids, src.creator_id = ids, (ids[0] if ids else None)


def _check_creators(s: Session, ids: list[int] | None) -> None:
    for i in ids or []:
        if not s.get(Creator, i):
            raise ApiError(422, "validation", "Creator not found")


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
    ids = body.creator_ids if body.creator_ids is not None else ([body.creator_id] if body.creator_id else [])
    _check_creators(s, ids)
    src = SourceAccount(platform=parsed.platform, username=parsed.username, profile_url=parsed.profile_url,
                        folder_id=body.folder_id, notes=body.notes)
    _set_creators(src, ids)
    s.add(src)
    s.flush()
    s.refresh(src)
    audit(s, "source.added", "source", src.id, {"platform": src.platform, "username": src.username})
    return ser.source(src, 0, {c.id: c for c in s.scalars(select(Creator))})


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
        # "Streamer A|Streamer B" in the creator column = an account that clips both.
        cids = [_get_or_create_creator(s, n.strip()).id for n in r["creator"].split("|") if n.strip()] if r.get("creator") else ([creator_id] if creator_id else [])
        fid = folder_id
        if r.get("folder"):
            f = s.scalar(select(Folder).where(func.lower(Folder.name) == r["folder"].lower()))
            if not f:
                f = Folder(name=r["folder"])
                s.add(f)
                s.flush()
            fid = f.id
        src = SourceAccount(platform=p.platform, username=p.username, profile_url=p.profile_url, folder_id=fid)
        _set_creators(src, cids)
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
    if "creator_ids" in data or "creator_id" in data:
        ids = data.pop("creator_ids", None)
        one = data.pop("creator_id", None)
        if ids is None:
            ids = [one] if one else []
        _check_creators(s, ids)
        _set_creators(src, ids)
    for k, v in data.items():
        setattr(src, k, v)
    s.flush()
    s.refresh(src)
    if "monitoring" in data:
        audit(s, f"source.{'resumed' if src.monitoring == 'active' else 'paused'}", "source", sid)
    return ser.source(src, _page_count(s, src), {c.id: c for c in s.scalars(select(Creator))})


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
            _set_creators(src, [body.creator_id] if body.creator_id else [])
            src.folder_id = body.folder_id
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
    creator_ids: list[int] | None = Field(None, max_length=50)


class DestinationPatch(BaseModel):
    display_name: str | None = Field(None, min_length=1, max_length=200)
    handle: str | None = Field(None, max_length=100)
    creator_id: int | None = None
    creator_ids: list[int] | None = Field(None, max_length=50)
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


def _dest_ids(s: Session, ids: list[int]) -> list[int]:
    ids = list(dict.fromkeys(int(i) for i in ids))
    for i in ids:
        _check_refs(s, i, None)
    return ids


@router.get("/destinations")
def list_destinations(platform: str | None = None, creator_id: int | None = None, s: Session = Depends(db)):
    stmt = select(DestinationAccount).order_by(DestinationAccount.platform, DestinationAccount.display_name)
    if platform:
        stmt = stmt.where(DestinationAccount.platform == platform)
    from ..routing import destination_creator_ids
    return [ser.destination(d) for d in s.scalars(stmt).unique()
            if not creator_id or creator_id in destination_creator_ids(d)]


@router.post("/destinations", status_code=201)
def add_destination_draft(body: DestinationDraftIn, s: Session = Depends(db)):
    """Add a page you post to. You upload to it yourself, so no login is needed."""
    if body.platform not in DESTINATION_PLATFORMS:
        raise ApiError(422, "validation", "Unsupported platform")
    ids = _dest_ids(s, body.creator_ids if body.creator_ids is not None else ([body.creator_id] if body.creator_id else []))
    d = DestinationAccount(platform=body.platform, external_id=f"manual:{uuid.uuid4().hex}", display_name=body.display_name.strip(),
                           handle=_handle(body.handle), creator_id=ids[0] if ids else None, creator_ids=ids,
                           settings=default_destination_settings(body.platform))
    s.add(d)
    s.flush()
    s.refresh(d)
    audit(s, "destination.created", "destination", d.id, {"platform": d.platform})
    return ser.destination(d)


@router.patch("/destinations/{did}")
def update_destination(did: int, body: DestinationPatch, s: Session = Depends(db)):
    d = get_or_404(s, DestinationAccount, did, "Destination account")
    data = body.model_dump(exclude_unset=True)
    if "creator_ids" in data or "creator_id" in data:
        ids = data.pop("creator_ids", None)
        one = data.pop("creator_id", None)
        ids = _dest_ids(s, ids if ids is not None else ([one] if one else []))
        d.creator_ids, d.creator_id = ids, (ids[0] if ids else None)
    if "settings" in data:
        try:
            merged = deep_merge(ser.normalized_settings(d.settings), data.pop("settings") or {})
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
    return ser.destination(d)


@router.delete("/destinations/{did}", status_code=204)
def delete_destination(did: int, s: Session = Depends(db), c=Depends(ctx)):
    d = get_or_404(s, DestinationAccount, did, "Destination account")
    c.secrets.delete(f"account:{d.platform}:{d.external_id}")
    audit(s, "destination.removed", "destination", did, {"platform": d.platform, "name": d.display_name})
    s.delete(d)

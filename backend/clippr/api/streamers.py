"""Streamers as sources: a streamer's stream link(s), and the pages their clips are posted to.

One streamer here ties together what Vyral keeps separately underneath: the streamer (whose saved streams are
searched), a watched channel for each Twitch or Kick link (its most-watched new clips become videos), and the
pages that take that streamer's clips. Changing one here keeps the others in step.
"""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from ..audit import audit
from ..fetch import is_single_video
from ..models import Clip, Creator, DestinationAccount, ReferenceVideo, SourceAccount
from ..platforms.urls import SourceInputError, parse_source_input
from ..routing import destination_creator_ids, source_creator_ids
from .accounts import _clean_channels
from .deps import ApiError, db, get_or_404

router = APIRouter()
WATCHED = ("twitch", "kick")  # channels whose own clips are watched


def _iso(d: datetime | None) -> str | None:
    return d.isoformat() if d else None


def _watched(s: Session, cid: int) -> list[SourceAccount]:
    """The channels watched for this streamer alone (an account covering several streamers isn't theirs to change)."""
    return [x for x in s.scalars(select(SourceAccount).where(SourceAccount.platform.in_(WATCHED))).unique()
            if source_creator_ids(x) == [cid]]


def _out(s: Session, c: Creator, pages: list[DestinationAccount]) -> dict:
    watched = _watched(s, c.id)
    return {
        "id": c.id, "name": c.name, "color": c.color, "links": list(c.vod_channels or []),
        "destination_ids": [d.id for d in pages if c.id in destination_creator_ids(d)],
        "watching": any(w.monitoring == "active" for w in watched),
        "channels": [{"id": w.id, "platform": w.platform, "username": w.username, "monitoring": w.monitoring,
                      "last_check": _iso(w.last_synced_at), "next_check": _iso(w.next_check_at), "error": w.last_error} for w in watched],
        "posts": s.scalar(select(func.count()).select_from(ReferenceVideo).where(
            ReferenceVideo.creator_id == c.id, ReferenceVideo.status != "baseline")) or 0,
        "clips": s.scalar(select(func.count()).select_from(Clip).where(Clip.creator_id == c.id)) or 0,
    }


def _pages(s: Session) -> list[DestinationAccount]:
    return list(s.scalars(select(DestinationAccount)).unique())


def _set_pages(s: Session, cid: int, wanted: list[int]) -> None:
    """Exactly these pages take this streamer's clips; other streamers on each page are kept."""
    pages = _pages(s)
    known = {d.id for d in pages}
    missing = [i for i in wanted if i not in known]
    if missing:
        raise ApiError(422, "validation", "One of those pages doesn't exist any more")
    for d in pages:
        ids = destination_creator_ids(d)
        if d.id in wanted and cid not in ids:
            ids = [*ids, cid]
        elif d.id not in wanted and cid in ids:
            ids = [i for i in ids if i != cid]
        else:
            continue
        d.creator_ids, d.creator_id = ids, (ids[0] if ids else None)


def _sync_channels(s: Session, c: Creator, watching: bool = True) -> None:
    """A watched channel for each Twitch or Kick channel link; channels whose link was removed stop being watched."""
    wanted = set()
    for link in c.vod_channels or []:
        if is_single_video(link):
            continue  # a single stream link is searched, not watched
        try:
            parsed = parse_source_input(link, "twitch")
        except SourceInputError:
            continue
        if parsed.platform not in WATCHED:
            continue  # YouTube channels: their streams are searched; there are no viewer clips to watch
        wanted.add((parsed.platform, parsed.username))
        src = s.scalar(select(SourceAccount).where(SourceAccount.platform == parsed.platform, SourceAccount.username == parsed.username))
        if not src:
            src = SourceAccount(platform=parsed.platform, username=parsed.username, profile_url=parsed.profile_url,
                                monitoring="active" if watching else "paused", notes="")
            s.add(src)
        if c.id not in source_creator_ids(src):
            ids = [*source_creator_ids(src), c.id]
            src.creator_ids, src.creator_id = ids, ids[0]
    for w in _watched(s, c.id):
        if (w.platform, w.username) not in wanted:
            s.delete(w)
    s.flush()


class StreamerIn(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    links: list[str] = Field(min_length=1, max_length=10)
    destination_ids: list[int] = Field(default_factory=list, max_length=100)
    permission: bool = False  # the user confirms they may clip this streamer


class StreamerPatch(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=120)
    links: list[str] | None = Field(None, min_length=1, max_length=10)
    destination_ids: list[int] | None = Field(None, max_length=100)
    watching: bool | None = None


@router.get("/streamers")
def list_streamers(s: Session = Depends(db)):
    pages = _pages(s)
    return [_out(s, c, pages) for c in s.scalars(select(Creator).order_by(Creator.name))]


@router.post("/streamers", status_code=201)
def add_streamer(body: StreamerIn, s: Session = Depends(db)):
    if not body.permission:
        raise ApiError(422, "permission", "Confirm you have permission to clip this streamer")
    links = _clean_channels(body.links)
    if not links:
        raise ApiError(422, "invalid_input", "Add the streamer's Twitch, Kick or YouTube channel link")
    c = Creator(name=body.name.strip(), vod_channels=links, clip_permission=True)
    s.add(c)
    try:
        s.flush()
    except IntegrityError:
        raise ApiError(409, "duplicate", "You already have a streamer with that name")
    _sync_channels(s, c)
    _set_pages(s, c.id, body.destination_ids)
    audit(s, "streamer.added", "creator", c.id, {"links": len(links), "pages": len(body.destination_ids)})
    return _out(s, c, _pages(s))


@router.patch("/streamers/{cid}")
def update_streamer(cid: int, body: StreamerPatch, s: Session = Depends(db)):
    c = get_or_404(s, Creator, cid, "Streamer")
    if body.name is not None:
        c.name = body.name.strip()
    if body.links is not None:
        c.vod_channels = _clean_channels(body.links)
        _sync_channels(s, c, watching=any(w.monitoring == "active" for w in _watched(s, cid)) or not _watched(s, cid))
    if body.destination_ids is not None:
        _set_pages(s, cid, body.destination_ids)
    if body.watching is not None:
        if body.watching and not _watched(s, cid):
            _sync_channels(s, c)  # a streamer from before: start watching their Twitch or Kick channel now
        for w in _watched(s, cid):
            w.monitoring = "active" if body.watching else "paused"
    try:
        s.flush()
    except IntegrityError:
        raise ApiError(409, "duplicate", "You already have a streamer with that name")
    return _out(s, c, _pages(s))


@router.delete("/streamers/{cid}", status_code=204)
def remove_streamer(cid: int, s: Session = Depends(db)):
    """Removes the streamer and the channels watched for them. Clips already made stay in Ready to Upload."""
    c = get_or_404(s, Creator, cid, "Streamer")
    for w in _watched(s, cid):
        s.delete(w)
    _set_pages(s, cid, [])
    audit(s, "streamer.removed", "creator", cid, {"name": c.name})
    s.delete(c)

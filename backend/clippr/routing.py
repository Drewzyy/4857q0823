"""Account funnel rules: which destinations a source's clips may flow to.

Invariant: a route between accounts of two different creators exists only if the user
explicitly confirmed it (`allow_cross_creator`). Accounts without a creator can be wired freely.
"""
from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from .audit import audit
from .models import DestinationAccount, FunnelRoute, SourceAccount


class RouteError(Exception):
    def __init__(self, message: str, code: str):
        super().__init__(message)
        self.code = code


def source_creator_ids(src: SourceAccount) -> list[int]:
    """All streamers a clipping account covers (most cover one; general accounts cover several)."""
    ids = [int(i) for i in (src.creator_ids or [])]
    if not ids and src.creator_id:
        ids = [src.creator_id]
    return ids


def creators_conflict(src: SourceAccount, dest: DestinationAccount) -> bool:
    ids = source_creator_ids(src)
    return bool(ids) and dest.creator_id is not None and dest.creator_id not in ids


def create_route(s: Session, source_id: int, destination_id: int, allow_cross_creator: bool = False) -> FunnelRoute:
    src, dest = s.get(SourceAccount, source_id), s.get(DestinationAccount, destination_id)
    if not src or not dest:
        raise RouteError("Source or destination not found", "not_found")
    if s.scalar(select(FunnelRoute).where(FunnelRoute.source_id == source_id, FunnelRoute.destination_id == destination_id)):
        raise RouteError(f"{src.username} already feeds {dest.display_name}", "duplicate")
    if creators_conflict(src, dest) and not allow_cross_creator:
        raise RouteError(
            f"{src.username} doesn't clip {dest.creator.name}, but {dest.display_name} belongs to {dest.creator.name}. Confirm to mix creators.",
            "cross_creator",
        )
    route = FunnelRoute(source_id=source_id, destination_id=destination_id, allow_cross_creator=creators_conflict(src, dest))
    s.add(route)
    s.flush()
    audit(s, "route.created", "route", route.id, {"source": src.username, "destination": dest.display_name, "cross_creator": route.allow_cross_creator})
    return route


def auto_route_by_creator(s: Session, creator_id: int | None = None) -> int:
    """IF creator = X THEN route every X source to every X destination. Returns routes created."""
    created = 0
    for src in s.scalars(select(SourceAccount)).unique():
        ids = source_creator_ids(src)
        if creator_id:
            ids = [i for i in ids if i == creator_id]
        if not ids:
            continue
        for dest in s.scalars(select(DestinationAccount).where(DestinationAccount.creator_id.in_(ids))).unique():
            exists = s.scalar(select(FunnelRoute).where(FunnelRoute.source_id == src.id, FunnelRoute.destination_id == dest.id))
            if not exists:
                s.add(FunnelRoute(source_id=src.id, destination_id=dest.id))
                created += 1
    s.flush()
    if created:
        audit(s, "route.auto_created", "creator", creator_id or "", {"count": created})
    return created


@dataclass
class ResolvedDestination:
    destination: DestinationAccount
    route_id: int


def resolve_destinations(s: Session, source_id: int) -> list[ResolvedDestination]:
    """Destinations a new clip from this source would be offered to. Disabled routes,
    disabled destinations and unconfirmed creator mismatches are excluded."""
    src = s.get(SourceAccount, source_id)
    if not src:
        return []
    out = []
    for r in s.scalars(select(FunnelRoute).where(FunnelRoute.source_id == source_id, FunnelRoute.enabled.is_(True))):
        dest = s.get(DestinationAccount, r.destination_id)
        if not dest or not dest.enabled:
            continue
        if creators_conflict(src, dest) and not r.allow_cross_creator:
            continue  # creator was reassigned after the route was made; don't silently mix
        out.append(ResolvedDestination(dest, r.id))
    return out

"""Visual account funnel: routes between source and destination accounts."""
from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import serialize as ser
from ..audit import audit
from ..models import DestinationAccount, FunnelRoute, Setting, SourceAccount
from ..routing import RouteError, auto_route_by_creator, create_route, creators_conflict, resolve_destinations
from .deps import ApiError, db, get_or_404

router = APIRouter(prefix="/funnel")
LAYOUT_KEY = "funnel_layout"


def _route(r: FunnelRoute, s: Session) -> dict:
    src, dest = s.get(SourceAccount, r.source_id), s.get(DestinationAccount, r.destination_id)
    return {"id": r.id, "source_id": r.source_id, "destination_id": r.destination_id, "enabled": r.enabled,
            "allow_cross_creator": r.allow_cross_creator,
            "blocked": bool(src and dest and creators_conflict(src, dest) and not r.allow_cross_creator)}


@router.get("")
def get_funnel(s: Session = Depends(db)):
    layout = s.get(Setting, LAYOUT_KEY)
    return {
        "sources": [ser.source(x) for x in s.scalars(select(SourceAccount).order_by(SourceAccount.username)).unique()],
        "destinations": [ser.destination(x) for x in s.scalars(select(DestinationAccount).order_by(DestinationAccount.display_name)).unique()],
        "routes": [_route(r, s) for r in s.scalars(select(FunnelRoute).order_by(FunnelRoute.id))],
        "layout": layout.value if layout else {},
    }


class RouteIn(BaseModel):
    source_id: int
    destination_id: int
    allow_cross_creator: bool = False


@router.post("/routes", status_code=201)
def add_route(body: RouteIn, s: Session = Depends(db)):
    try:
        r = create_route(s, body.source_id, body.destination_id, body.allow_cross_creator)
    except RouteError as e:
        raise ApiError(404 if e.code == "not_found" else 409, e.code, str(e))
    return _route(r, s)


class RoutePatch(BaseModel):
    enabled: bool | None = None
    allow_cross_creator: bool | None = None


@router.patch("/routes/{rid}")
def update_route(rid: int, body: RoutePatch, s: Session = Depends(db)):
    r = get_or_404(s, FunnelRoute, rid, "Route")
    for k, v in body.model_dump(exclude_none=True).items():
        setattr(r, k, v)
    audit(s, "route.updated", "route", rid, body.model_dump(exclude_none=True))
    return _route(r, s)


@router.delete("/routes/{rid}", status_code=204)
def delete_route(rid: int, s: Session = Depends(db)):
    r = get_or_404(s, FunnelRoute, rid, "Route")
    audit(s, "route.deleted", "route", rid)
    s.delete(r)


class AutoRouteIn(BaseModel):
    creator_id: int | None = None


@router.post("/auto-route")
def auto_route(body: AutoRouteIn, s: Session = Depends(db)):
    return {"created": auto_route_by_creator(s, body.creator_id)}


class LayoutIn(BaseModel):
    positions: dict[str, dict[str, float]] = Field(max_length=5000)


@router.put("/layout")
def save_layout(body: LayoutIn, s: Session = Depends(db)):
    clean = {k: {"x": float(v.get("x", 0)), "y": float(v.get("y", 0))} for k, v in body.positions.items() if len(k) < 40}
    row = s.get(Setting, LAYOUT_KEY)
    if row:
        row.value = clean
    else:
        s.add(Setting(key=LAYOUT_KEY, value=clean))
    return {"saved": len(clean)}


@router.get("/resolve/{source_id}")
def resolve(source_id: int, s: Session = Depends(db)):
    get_or_404(s, SourceAccount, source_id, "Source account")
    return [{"route_id": r.route_id, **ser.destination(r.destination)} for r in resolve_destinations(s, source_id)]

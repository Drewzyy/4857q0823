"""The app's side of review and publishing: approve or reject a page's video, send it to Postiz, connect Postiz,
and the MCP bridge's status (with its token, so you can give it to Muse). The rules live in ../posting.py."""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from .. import mcp, posting
from ..audit import audit
from ..postiz import SECRET, Postiz, PostizError
from .deps import ApiError, ctx, db
from .system import load_settings

router = APIRouter()


class ReviewIn(BaseModel):
    decision: Literal["approve", "reject"]
    reason: str = Field("", max_length=500)
    watched: bool = False
    caption: str | None = Field(None, max_length=2200)
    scheduled_at: datetime | None = None


@router.post("/outputs/{oid}/review")
def review(oid: int, body: ReviewIn, c=Depends(ctx), s: Session = Depends(db)):
    try:
        if body.decision == "approve":
            o = posting.approve(s, c.jobs, oid, "you", watched=body.watched, caption=body.caption, scheduled_at=body.scheduled_at)
        else:
            o = posting.reject(s, oid, "you", body.reason or "Rejected")
    except posting.PostingError as e:
        raise ApiError(409, "not_allowed", str(e))
    return {"id": o.id, "review": o.review, "review_note": o.review_note}


class SendIn(BaseModel):
    mode: Literal["draft", "schedule", "now"] = "draft"


@router.post("/outputs/{oid}/postiz")
def send(oid: int, body: SendIn, c=Depends(ctx), s: Session = Depends(db)):
    """Queued: the upload can take a minute. The video's Postiz state shows the outcome."""
    from ..models import ClipOutput
    o = s.get(ClipOutput, oid)
    if not o or o.review != "approved":
        raise ApiError(409, "not_allowed", "Approve it first")
    o.postiz_state, o.postiz_error = "sending", None
    c.jobs.enqueue("postiz.send", {"output_id": oid, "mode": body.mode, "by": "you"}, max_attempts=1, session=s)
    return {"queued": True}


class PostizIn(BaseModel):
    api_key: str = Field(min_length=8, max_length=400)


@router.get("/bridge")
def bridge(c=Depends(ctx), s: Session = Depends(db)):
    cfg = load_settings(s).posting
    state = c.mcp.state() if c.mcp else {"running": False, "port": None, "error": None}
    return {"mcp": {**state, "enabled": cfg.mcp_enabled, "url": f"http://127.0.0.1:{cfg.mcp_port}/mcp", "token": mcp.token(c)},
            "postiz": {"connected": bool((c.secrets.get(SECRET) or {}).get("api_key")), "url": cfg.postiz_url}}


@router.post("/bridge/restart")
def restart(c=Depends(ctx)):
    """After changing the MCP port or toggle in Settings."""
    if c.mcp:
        c.mcp.restart()
    return c.mcp.state() if c.mcp else {}


@router.put("/postiz")
def connect_postiz(body: PostizIn, c=Depends(ctx), s: Session = Depends(db)):
    """Checks the key against Postiz before keeping it (in the OS keychain, never in the database or logs)."""
    try:
        channels = Postiz(load_settings(s).posting.postiz_url, body.api_key.strip()).integrations()
    except PostizError as e:
        raise ApiError(422, "postiz", str(e))
    c.secrets.set(SECRET, {"api_key": body.api_key.strip()})
    audit(s, "postiz.connected", "settings", "postiz", {"channels": len(channels)})
    return {"connected": True, "channels": channels}


@router.get("/postiz/channels")
def channels(c=Depends(ctx), s: Session = Depends(db)):
    try:
        return posting.client(c, s).integrations()
    except PostizError as e:
        raise ApiError(422, "postiz", str(e))


@router.delete("/postiz", status_code=204)
def disconnect_postiz(c=Depends(ctx), s: Session = Depends(db)):
    c.secrets.delete(SECRET)
    audit(s, "postiz.disconnected", "settings", "postiz")

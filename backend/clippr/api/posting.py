"""The app's side of review and publishing: approve or reject a page's video, and the MCP bridge's status (with its token, so you can give it to Muse). The rules live in ../posting.py."""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from .. import mcp, posting
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
            o = posting.approve(s, oid, "you", watched=body.watched, caption=body.caption, scheduled_at=body.scheduled_at)
        else:
            o = posting.reject(s, oid, "you", body.reason or "Rejected")
    except posting.PostingError as e:
        raise ApiError(409, "not_allowed", str(e))
    return {"id": o.id, "review": o.review, "review_note": o.review_note}


@router.get("/bridge")
def bridge(c=Depends(ctx), s: Session = Depends(db)):
    cfg = load_settings(s).posting
    state = c.mcp.state() if c.mcp else {"running": False, "port": None, "error": None}
    return {"mcp": {**state, "enabled": cfg.mcp_enabled, "url": f"http://{cfg.mcp_host}:{cfg.mcp_port}/mcp", "host": cfg.mcp_host, "token": mcp.token(c)}}


@router.post("/bridge/restart")
def restart(c=Depends(ctx)):
    """After changing the MCP port or toggle in Settings."""
    if c.mcp:
        c.mcp.restart()
    return c.mcp.state() if c.mcp else {}

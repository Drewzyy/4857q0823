"""The app's side of review and publishing: approve or reject a page's video, and the MCP bridge's status (with its token, so you can give it to Muse). The rules live in ../posting.py."""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from .. import mcp, posting, screen, style
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


@router.get("/learned")
def get_learned(s: Session = Depends(db)):
    """What the screener has learned from your review notes (screen.py), with the note behind each change."""
    return screen.learned(s)


@router.post("/learned/reset")
def reset_learned(s: Session = Depends(db)):
    screen.reset(s)
    s.flush()
    return screen.learned(s)


class StyleLink(BaseModel):
    url: str = Field(min_length=8, max_length=500)


@router.get("/style")
def get_style(s: Session = Depends(db)):
    """Your style (style.py): every clip measured and what was learned from them."""
    return style.view(s)


@router.post("/style/learn")
def learn_style(body: StyleLink, c=Depends(ctx)):
    """Measure one of your clips (a TikTok, Reel or Short link) and add it to your style."""
    url = body.url.strip()
    if not url.startswith("https://"):
        raise ApiError(422, "invalid_input", "Paste the https link to the clip")
    c.jobs.enqueue("style.learn", {"url": url}, max_attempts=2)
    return {"queued": True}


@router.post("/style/forget")
def forget_style(body: StyleLink | None = None, s: Session = Depends(db)):
    """Forget one measured clip, or all of them (back to Vyral's own defaults)."""
    style.forget(s, body.url if body else None)
    return style.view(s)


@router.post("/style/apply")
def apply_style(c=Depends(ctx)):
    """Cut every waiting clip you didn't edit again to your style."""
    c.jobs.enqueue("style.apply", {}, max_attempts=1)
    return {"queued": True}

"""Settings for the Discord phone inbox (see discord_inbox.py)."""
from __future__ import annotations

import httpx
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from .. import discord_inbox as inbox
from ..audit import audit
from .deps import ApiError, ctx, db

router = APIRouter(prefix="/discord-inbox")


def _view(c, s) -> dict:
    st = c.inbox.state(s)
    return {"configured": bool(c.inbox.token()), "channel_id": st.get("channel_id"), "channel_name": st.get("channel_name"),
            "server": st.get("server"), "bot": st.get("bot"), "last_error": st.get("last_error"), "last_checked": st.get("last_checked")}


def _channels(token: str) -> dict:
    try:
        with httpx.Client(timeout=15) as http:
            return inbox.bot_channels(http, token)
    except inbox.InboxError as e:
        raise ApiError(422, "discord", str(e))
    except httpx.HTTPError:
        raise ApiError(502, "discord", "Couldn't reach Discord. Check your internet connection.")


@router.get("")
def get_inbox(c=Depends(ctx), s: Session = Depends(db)):
    return _view(c, s)


@router.get("/channels")
def list_channels(c=Depends(ctx)):
    token = c.inbox.token()
    if not token:
        raise ApiError(409, "not_configured", "Add the bot token first")
    return _channels(token)["channels"]


class InboxIn(BaseModel):
    token: str | None = Field(None, min_length=20, max_length=200)
    channel_id: str | None = Field(None, pattern=r"^\d{5,30}$")


@router.put("")
def set_inbox(body: InboxIn, c=Depends(ctx), s: Session = Depends(db)):
    if body.token:
        info = _channels(body.token.strip())  # proves the token works before it's kept
        c.secrets.set(inbox.SECRET_KEY, {"token": body.token.strip()})
        c.inbox.save_state(s, bot=info["bot"], last_error=None)
        audit(s, "discord_inbox.token_set", "settings")
    if body.channel_id:
        token = c.inbox.token()
        if not token:
            raise ApiError(409, "not_configured", "Add the bot token first")
        match = next((ch for ch in _channels(token)["channels"] if ch["id"] == body.channel_id), None)
        if not match:
            raise ApiError(422, "validation", "The bot can't see that channel")
        # Start reading from now on; links posted before this aren't treated as new requests.
        c.inbox.save_state(s, channel_id=match["id"], channel_name=match["name"], server=match["server"], last_message_id=None, last_error=None)
    return _view(c, s)


@router.delete("", status_code=204)
def remove_inbox(c=Depends(ctx), s: Session = Depends(db)):
    c.secrets.delete(inbox.SECRET_KEY)
    c.inbox.save_state(s, channel_id=None, channel_name=None, server=None, bot=None, last_message_id=None, last_error=None)
    audit(s, "discord_inbox.removed", "settings")

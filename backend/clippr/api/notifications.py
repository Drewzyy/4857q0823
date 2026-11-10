"""Discord settings and the event history (see events.py)."""
from __future__ import annotations

import re

import httpx
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session

from .. import events, notify
from ..audit import audit
from ..models import Setting
from .deps import ApiError, ctx, db

router = APIRouter()
HHMM = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")


def _hint(secrets, key: str) -> str | None:
    url = (secrets.get(key) or {}).get("url")
    return "…" + url[-6:] if url else None


def _state(s: Session, c) -> dict:
    p = events.prefs(s)
    return {
        "configured": bool(_hint(c.secrets, events.webhook_key(None))), "webhook_hint": _hint(c.secrets, events.webhook_key(None)),
        "categories": [{"key": k, "label": label, "enabled": p["categories"][k], "own_webhook_hint": _hint(c.secrets, events.webhook_key(k))}
                       for k, label in events.CATEGORIES.items()],
        "min_priority": p["min_priority"], "quiet_start": p["quiet_start"], "quiet_end": p["quiet_end"],
    }


class NotifyIn(BaseModel):
    webhook_url: str | None = Field(None, max_length=300)  # the default channel
    category_webhooks: dict[str, str] | None = None  # category -> its own channel; "" goes back to the default
    categories: dict[str, bool] | None = None
    min_priority: str | None = None
    quiet_start: str | None = None  # "23:00"; "" turns quiet hours off
    quiet_end: str | None = None

    @field_validator("category_webhooks", "categories")
    @classmethod
    def _known(cls, v):
        if v and set(v) - set(events.CATEGORIES):
            raise ValueError(f"unknown category: {', '.join(sorted(set(v) - set(events.CATEGORIES)))}")
        return v

    @field_validator("min_priority")
    @classmethod
    def _priority(cls, v):
        if v is not None and v not in events.PRIORITIES:
            raise ValueError("must be low, normal, high or urgent")
        return v

    @field_validator("quiet_start", "quiet_end")
    @classmethod
    def _time(cls, v):
        if v and not HHMM.match(v):
            raise ValueError("use a time like 23:00")
        return v


def _check_hook(url: str) -> str:
    url = url.strip()
    if not notify.valid_webhook(url):
        raise ApiError(422, "invalid_webhook", "That isn't a Discord webhook link. In Discord: channel settings > Integrations > Webhooks > Copy Webhook URL.")
    return url


@router.get("/notifications")
def get_notifications(s: Session = Depends(db), c=Depends(ctx)):
    return _state(s, c)


@router.put("/notifications")
def put_notifications(body: NotifyIn, s: Session = Depends(db), c=Depends(ctx)):
    if body.webhook_url is not None:
        c.secrets.set(events.webhook_key(None), {"url": _check_hook(body.webhook_url)})
        audit(s, "notifications.webhook_set", "settings")
    for cat, url in (body.category_webhooks or {}).items():
        if url.strip():
            c.secrets.set(events.webhook_key(cat), {"url": _check_hook(url)})
        else:
            c.secrets.delete(events.webhook_key(cat))
        audit(s, "notifications.channel_set", "settings", cat)
    p = events.prefs(s)
    if body.categories:
        p["categories"].update(body.categories)
    for k in ("min_priority", "quiet_start", "quiet_end"):
        v = getattr(body, k)
        if v is not None:
            p[k] = v or None
    if bool(p["quiet_start"]) != bool(p["quiet_end"]):
        raise ApiError(422, "validation", "Quiet hours need both a start and an end time")
    row = s.get(Setting, notify.SETTINGS_KEY)
    if row:
        row.value = p
    else:
        s.add(Setting(key=notify.SETTINGS_KEY, value=p))
    s.flush()
    return _state(s, c)


@router.delete("/notifications/webhook", status_code=204)
def delete_webhooks(s: Session = Depends(db), c=Depends(ctx)):
    """Disconnect Discord: the default channel and every category's own channel."""
    for key in [events.webhook_key(None), *(events.webhook_key(k) for k in events.CATEGORIES)]:
        c.secrets.delete(key)
    audit(s, "notifications.webhook_removed", "settings")


class TestIn(BaseModel):
    category: str | None = None


@router.post("/notifications/test")
def test_notification(body: TestIn | None = None, c=Depends(ctx)):
    category = body.category if body else None
    if category and category not in events.CATEGORIES:
        raise ApiError(422, "validation", "Unknown category")
    hook = events.webhook_for(c.secrets, category) if category else (c.secrets.get(events.webhook_key(None)) or {}).get("url")
    if not hook:
        raise ApiError(409, "not_configured", "Add a Discord webhook first")
    where = events.CATEGORIES[category] if category else "everything without its own channel"
    try:
        with httpx.Client(timeout=15) as http:
            notify.send(http, hook, {"content": f"👋 Vyral is connected. This channel gets: {where}."})
    except notify.NotifyError as e:
        raise ApiError(502, "discord_error", str(e))
    except httpx.HTTPError:
        raise ApiError(502, "network", "Couldn't reach Discord. Check your internet connection.")
    return {"sent": True}


@router.get("/events")
def list_events(limit: int = 50, category: str | None = None, s: Session = Depends(db)):
    return [{"id": e.id, "ts": e.ts.isoformat(), "category": e.category, "priority": e.priority, "title": e.title, "body": e.body,
             "link": e.link, "delivery": e.delivery, "delivery_error": e.delivery_error}
            for e in events.recent(s, max(1, min(limit, 200)), category)]

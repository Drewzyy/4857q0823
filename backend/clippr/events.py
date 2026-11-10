"""Notification Service: everything worth knowing goes through `emit`.

Each event is stored (Vyral's history, the dashboard's recent activity) and, if the user's preferences allow,
delivered to Discord: per category, to that category's own webhook or the default one, after quiet hours unless
it's urgent, and never twice for the same thing (dedupe_key). Delivery runs as a background job with retries, so
a Discord outage never blocks anything else. Webhook URLs live in the secret store, never in events or logs.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

from . import notify
from .jobs import PermanentJobError
from .models import Event, Setting

CATEGORIES = {
    "opportunities": "Campaign opportunities",
    "approvals": "Approvals and clips ready",
    "production": "Content production",
    "agents": "Agent activity",
    "analytics": "Account analytics",
    "earnings": "Earnings",
    "system": "System health",
}
PRIORITIES = ("low", "normal", "high", "urgent")
COLORS = {"low": 0x6B7280, "normal": 0x8B5CF6, "high": 0xD9A441, "urgent": 0xE5484D}
DEFAULT_PREFS: dict[str, Any] = {"categories": {c: True for c in CATEGORIES}, "min_priority": "low", "quiet_start": None, "quiet_end": None}


def webhook_key(category: str | None) -> str:
    return f"{notify.SECRET_KEY}:{category}" if category else notify.SECRET_KEY


def webhook_for(secrets, category: str) -> str | None:
    """The category's own webhook if it has one, else the default."""
    return (secrets.get(webhook_key(category)) or secrets.get(notify.SECRET_KEY) or {}).get("url")


def prefs(s) -> dict[str, Any]:
    row = s.get(Setting, notify.SETTINGS_KEY)
    saved = row.value if row else {}
    return {**DEFAULT_PREFS, **{k: v for k, v in saved.items() if k in DEFAULT_PREFS},
            "categories": {**DEFAULT_PREFS["categories"], **(saved.get("categories") or {})}}


def _minutes(hhmm: str) -> int:
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)


def quiet_delay(p: dict[str, Any], now: datetime) -> float:
    """Seconds until quiet hours end (0 outside them). Times are the computer's local time."""
    if not p.get("quiet_start") or not p.get("quiet_end"):
        return 0
    local = now.astimezone()
    t, start, end = local.hour * 60 + local.minute, _minutes(p["quiet_start"]), _minutes(p["quiet_end"])
    quiet = start <= t < end if start < end else (t >= start or t < end)
    if not quiet:
        return 0
    return ((end - t) % (24 * 60)) * 60 - local.second


def emit(ctx, category: str, title: str, *, body: str = "", priority: str = "normal", link: str | None = None,
         dedupe_key: str | None = None, data: dict | None = None, discord: dict | None = None) -> int | None:
    """Record an event and queue its Discord delivery. Returns None if this exact event was already recorded."""
    assert category in CATEGORIES and priority in PRIORITIES, (category, priority)
    with ctx.db.session() as s:
        if dedupe_key and s.query(Event.id).filter(Event.dedupe_key == dedupe_key).first():
            return None
        ev = Event(category=category, priority=priority, title=title[:300], body=body, link=link, dedupe_key=dedupe_key,
                   data={**(data or {}), **({"discord": discord} if discord else {})})
        s.add(ev)
        s.flush()
        p = prefs(s)
        if not webhook_for(ctx.secrets, category):
            ev.delivery = "none"
        elif not p["categories"].get(category, True) or PRIORITIES.index(priority) < PRIORITIES.index(p["min_priority"]):
            ev.delivery = "off"
        else:
            delay = 0 if priority == "urgent" else quiet_delay(p, datetime.now(timezone.utc))
            ev.delivery = "held" if delay else "queued"
            ctx.jobs.enqueue("notify.discord", {"event_id": ev.id}, max_attempts=4, delay=delay, session=s)
        return ev.id


def payload(ev: Event) -> dict:
    """The event as a Discord message: its own formatted message if it brought one, else a standard embed."""
    if ev.data.get("discord"):
        return ev.data["discord"]
    embed: dict[str, Any] = {"title": ev.title[:250], "description": ev.body[:3900], "color": COLORS.get(ev.priority, COLORS["normal"]),
                             "footer": {"text": CATEGORIES.get(ev.category, ev.category)}}
    if ev.link:
        embed["url"] = ev.link
    return {"embeds": [embed]}


def deliver(ctx, event_id: int) -> dict:
    with ctx.db.session() as s:
        ev = s.get(Event, event_id)
        if not ev:
            return {"skipped": "gone"}
        hook, message = webhook_for(ctx.secrets, ev.category), payload(ev)
    if not hook:
        return _mark(ctx, event_id, "none")
    try:
        with httpx.Client(timeout=15) as http:
            notify.send(http, hook, message)
    except notify.NotifyError as e:
        _mark(ctx, event_id, "failed", str(e))
        if "rejected" in str(e):
            raise PermanentJobError(str(e))
        raise
    except httpx.HTTPError as e:
        _mark(ctx, event_id, "failed", f"Couldn't reach Discord ({type(e).__name__})")
        raise
    return _mark(ctx, event_id, "sent")


def _mark(ctx, event_id: int, delivery: str, error: str | None = None) -> dict:
    with ctx.db.session() as s:
        ev = s.get(Event, event_id)
        if ev:
            ev.delivery, ev.delivery_error = delivery, error
            if delivery == "sent":
                ev.delivered_at = datetime.now(timezone.utc)
    return {"delivery": delivery}


def recent(s, limit: int = 50, category: str | None = None) -> list[Event]:
    q = s.query(Event)
    if category:
        q = q.filter(Event.category == category)
    return q.order_by(Event.ts.desc(), Event.id.desc()).limit(limit).all()


def cleanup(ctx, keep_days: int = 90) -> int:
    with ctx.db.session() as s:
        return s.query(Event).filter(Event.ts < datetime.now(timezone.utc) - timedelta(days=keep_days)).delete()

"""Phone inbox: post TikTok links in a Discord channel, optionally with the streamer's name, and Vyral clips them.

Discord webhooks can only send, so reading the channel takes a small bot the user creates once (free). Its token
is kept with the other secrets and never logged. The channel is read every few seconds while Vyral runs; each
message with a video link gets a ✅ reaction once it's queued.
"""
from __future__ import annotations

import logging
import threading
import time
from typing import Any
from urllib.parse import quote

import httpx
from sqlalchemy import select

from . import identify
from .fetch import VIDEO_LINK
from .models import Creator, Setting

log = logging.getLogger("clippr.discord_inbox")

API = "https://discord.com/api/v10"
SECRET_KEY = "discord:bot"
SETTINGS_KEY = "discord_inbox"
POLL_SECONDS = 8
NO_CONTENT = ("Discord isn't sharing message text with the bot. In the Discord developer page, open your bot's "
              "Bot tab and turn on Message Content Intent.")


class InboxError(Exception):
    pass


def _call(http: httpx.Client, token: str, method: str, path: str) -> Any:
    for attempt in range(2):
        r = http.request(method, API + path, headers={"Authorization": f"Bot {token}"})
        if r.status_code == 429 and attempt == 0:
            time.sleep(min(float(r.json().get("retry_after", 1)), 5))
            continue
        if r.status_code == 401:
            raise InboxError("Discord didn't accept the bot token. Copy a fresh one from the bot's Bot tab (Reset Token).")
        if r.status_code in (403, 404):
            raise InboxError("The bot can't read that channel. Make sure it was added to your server and can view the channel.")
        if r.status_code >= 400:
            raise InboxError(f"Discord returned HTTP {r.status_code}")
        return r.json() if r.content else None
    raise InboxError("Discord is rate limiting the bot; it'll try again shortly.")


def bot_channels(http: httpx.Client, token: str) -> dict:
    """The bot's name and every text channel it can see, for the setup screen."""
    me = _call(http, token, "GET", "/users/@me")
    channels = []
    for g in _call(http, token, "GET", "/users/@me/guilds") or []:
        for ch in _call(http, token, "GET", f"/guilds/{g['id']}/channels") or []:
            if ch.get("type") == 0:  # text channel
                channels.append({"id": ch["id"], "name": ch["name"], "server": g["name"]})
    return {"bot": me.get("username", "bot"), "channels": channels}


def parse(content: str, creators: list[tuple[int, str, list[str]]]) -> list[tuple[str, int | None]]:
    """Video links in a message, each with the streamer the rest of the message names (if any)."""
    words = content.replace("<", " ").replace(">", " ").split()  # Discord wraps links in <> to hide previews
    links = list(dict.fromkeys(w for w in words if VIDEO_LINK.match(w)))
    hint = " ".join(w for w in words if not w.startswith("http"))
    best, best_score = None, 0
    for cid, name, channels in (creators if hint else []):
        score = max([identify.mention_score(name, hint)] + [identify.mention_score(identify.channel_handle(ch), hint) for ch in channels])
        if score > best_score:
            best, best_score = cid, score
    return [(link, best) for link in links]


class DiscordInbox:
    def __init__(self, ctx: Any):
        self.ctx = ctx
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def state(self, s) -> dict:
        row = s.get(Setting, SETTINGS_KEY)
        return dict(row.value) if row else {}

    def save_state(self, s, **changes) -> dict:
        row = s.get(Setting, SETTINGS_KEY)
        value = {**(row.value if row else {}), **changes}
        if row:
            row.value = value
        else:
            s.add(Setting(key=SETTINGS_KEY, value=value))
        return value

    def token(self) -> str | None:
        return (self.ctx.secrets.get(SECRET_KEY) or {}).get("token")

    def poll(self) -> dict:
        token = self.token()
        with self.ctx.db.session() as s:
            st = self.state(s)
            creators = [(c.id, c.name, list(c.vod_channels or [])) for c in s.scalars(select(Creator))]
        channel = st.get("channel_id")
        if not token or not channel:
            return {"skipped": "not set up"}
        try:
            with httpx.Client(timeout=15) as http:
                after = st.get("last_message_id")
                if not after:  # start from now: older messages in the channel aren't new requests
                    latest = _call(http, token, "GET", f"/channels/{channel}/messages?limit=1") or []
                    with self.ctx.db.session() as s:
                        self.save_state(s, last_message_id=latest[0]["id"] if latest else "0", last_error=None)
                    return {"started": True}
                messages = sorted(_call(http, token, "GET", f"/channels/{channel}/messages?after={after}&limit=50") or [],
                                  key=lambda m: int(m["id"]))
                queued, error, unrecognized = 0, None, st.get("last_unrecognized")
                for m in messages:
                    after = m["id"]
                    if m.get("author", {}).get("bot") or m.get("webhook_id"):
                        continue  # Vyral's own notifications and other bots
                    content = m.get("content") or ""
                    if not content and not m.get("attachments") and not m.get("embeds"):
                        error = NO_CONTENT
                        continue
                    found = parse(content, creators)
                    for link, creator_id in found:
                        self.ctx.jobs.enqueue("intake.link", {"url": link, "creator_id": creator_id}, max_attempts=3)
                    queued += len(found)
                    if not found:  # shown in Settings so it's clear what the bot saw
                        unrecognized = content[:200]
                    emoji = quote("✅" if found else "❓")
                    try:
                        _call(http, token, "PUT", f"/channels/{channel}/messages/{m['id']}/reactions/{emoji}/@me")
                    except InboxError:
                        pass  # a missing reaction permission shouldn't stop the inbox
        except (InboxError, httpx.HTTPError) as e:
            with self.ctx.db.session() as s:
                self.save_state(s, last_error=str(e) if isinstance(e, InboxError) else "Couldn't reach Discord")
            return {"error": str(e)}
        with self.ctx.db.session() as s:
            self.save_state(s, last_message_id=after, last_error=error, last_checked=time.time(), last_unrecognized=unrecognized)
        return {"queued": queued}

    def start(self) -> None:
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="discord-inbox", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()

    def _run(self) -> None:
        while not self._stop.wait(POLL_SECONDS):
            try:
                self.poll()
            except Exception:  # never let a surprise kill the loop
                log.exception("discord inbox check failed")

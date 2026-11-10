"""Discord webhook notifications."""
from __future__ import annotations

import re
import time
from typing import Any

import httpx


WEBHOOK_RE = re.compile(r"^https://(?:(?:ptb|canary)\.)?discord(?:app)?\.com/api/webhooks/\d{5,30}/[A-Za-z0-9_\-]{20,200}$")
SECRET_KEY = "discord:webhook"
SETTINGS_KEY = "notifications"
PLATFORM = {"tiktok": "TikTok", "instagram": "Instagram", "youtube": "YouTube", "facebook": "Facebook"}


class NotifyError(Exception):
    pass


def valid_webhook(url: str) -> bool:
    return bool(WEBHOOK_RE.match(url.strip()))


def send(http: httpx.Client, url: str, payload: dict[str, Any]) -> None:
    for attempt in range(3):
        r = http.post(url, json={**payload, "allowed_mentions": {"parse": []}, "username": "Vyral"})
        if r.status_code in (200, 204):
            return
        if r.status_code == 429 and attempt < 2:
            try:
                wait = float(r.json().get("retry_after", 2))
            except ValueError:
                wait = 2.0
            time.sleep(min(wait, 10))
            continue
        if r.status_code in (401, 403, 404):
            raise NotifyError("Discord rejected the webhook. It may have been deleted; paste a new one in Settings > Notifications.")
        raise NotifyError(f"Discord returned HTTP {r.status_code}")


def new_post_message(account: str, platform: str, title: str, url: str, thumb: str | None) -> dict:
    embed: dict[str, Any] = {"title": (title or "New video")[:250], "url": url, "color": 0x8B5CF6,
                             "footer": {"text": f"@{account} on {PLATFORM.get(platform, platform)}"}}
    if thumb:
        embed["thumbnail"] = {"url": thumb}
    return {"content": f"📥 **@{account}** just posted a new video. Vyral is making a clip.", "embeds": [embed]}


def ready_message(title: str, creator: str | None, targets: list[tuple[str, str, str]], graded: dict | None = None) -> dict:
    """targets: (platform, destination name, handle). graded: the clip's grade, if it has one."""
    head = f"**{graded['tier']} tier** ({graded['score']}/100). " if graded else ""
    lines = [f"• **{PLATFORM.get(p, p)}**: {name}" + (f" ({h if h.startswith('@') else '@' + h})" if h else "") for p, name, h in targets]
    return {"content": "✅ **Clip ready for upload**" + (f" ({creator})" if creator else ""),
            "embeds": [{"title": (title or "New clip")[:250], "description": (head + "\n" if head else "") + "\n".join(lines)[:3800], "color": 0x3FB67A,
                        "footer": {"text": "Open Vyral > Ready to Upload to download it with the caption"}}]}


def problem_message(account: str | None, reason: str, url: str | None) -> dict:
    who = f"@{account}'s new video" if account else "a video"
    embed = {"description": reason[:1000], "color": 0xD9A441}
    if url:
        embed["url"] = url
        embed["title"] = "Original post"
    return {"content": f"⚠️ Vyral couldn't make a clip from {who}.", "embeds": [embed]}

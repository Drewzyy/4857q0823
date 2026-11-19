"""Postiz, the publishing backend: Vyral hands it an approved clip and reads back where it went.

Uses Postiz's public API (https://api.postiz.com/public/v1, or your own Postiz's address in Settings):
GET /integrations (your connected channels), POST /upload (the video, multipart field "file"), POST /posts
(draft, scheduled or now) and GET /posts (state, URL, error). The API key is sent raw in the Authorization
header, as Postiz expects. It's kept in the OS keychain (secrets_store) and never logged or returned.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx

SECRET = "postiz"  # secrets_store key: {"api_key": "..."}
TIMEOUT = httpx.Timeout(30, read=600)  # uploads of big videos take a while


class PostizError(Exception):
    pass


def _settings(provider: str, title: str) -> dict:
    """Per-platform post settings, as Postiz's providers read them."""
    if provider.startswith("tiktok"):
        # DIRECT_POST publishes (UPLOAD only drops it in the TikTok inbox); everything else needs DIRECT_POST.
        return {"__type": provider, "title": title[:90], "privacy_level": "PUBLIC_TO_EVERYONE", "duet": True, "stitch": True,
                "comment": True, "autoAddMusic": "no", "brand_content_toggle": False, "brand_organic_toggle": False,
                "video_made_with_ai": False, "content_posting_method": "DIRECT_POST"}
    if provider.startswith("instagram"):
        return {"__type": provider, "post_type": "post", "collaborators": []}  # one video as a post is a Reel
    return {"__type": provider}


class Postiz:
    def __init__(self, base_url: str, api_key: str, client: httpx.Client | None = None):
        if not api_key:
            raise PostizError("Postiz isn't connected: add your Postiz API key in Settings")
        self.base = base_url.rstrip("/") + "/public/v1"
        self.http = client or httpx.Client(timeout=TIMEOUT, headers={"Authorization": api_key})

    def _call(self, method: str, path: str, **kw):
        try:
            r = self.http.request(method, self.base + path, **kw)
        except httpx.HTTPError as e:
            raise PostizError(f"Couldn't reach Postiz ({type(e).__name__})")
        if r.status_code == 401:
            raise PostizError("Postiz turned down the API key: check it in Settings")
        if r.status_code >= 400:
            try:
                msg = r.json().get("msg") or r.json().get("message") or r.text
            except ValueError:
                msg = r.text
            raise PostizError(f"Postiz said {r.status_code}: {str(msg)[:300]}")
        return r.json() if r.content else {}

    def integrations(self) -> list[dict]:
        """Your Postiz channels: id, name, provider (tiktok, instagram, ...), picture, disabled."""
        return [{"id": i.get("id"), "name": i.get("name"), "provider": i.get("identifier") or i.get("providerIdentifier") or "",
                 "picture": i.get("picture"), "disabled": bool(i.get("disabled")), "profile": i.get("profile")}
                for i in self._call("GET", "/integrations") or []]

    def upload(self, video: Path) -> dict:
        with video.open("rb") as f:
            media = self._call("POST", "/upload", files={"file": (video.name, f, "video/mp4")})
        if not media.get("path"):
            raise PostizError("Postiz didn't return the uploaded video")
        return {"id": media.get("id"), "path": media["path"]}

    def create(self, *, integration: dict, video: Path, caption: str, title: str, mode: str, when: datetime | None) -> str:
        """Posts (or drafts, or schedules) one video on one channel. Returns Postiz's post id."""
        if mode not in ("draft", "schedule", "now"):
            raise PostizError(f"Unknown post mode {mode!r}")
        media = self.upload(video)
        date = (when or datetime.now(timezone.utc)).astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")
        body = {"type": mode, "date": date, "shortLink": False, "tags": [],
                "posts": [{"integration": {"id": integration["id"]}, "value": [{"content": caption, "image": [media]}],
                           "settings": _settings(integration["provider"], title)}]}
        out = self._call("POST", "/posts", json=body)
        first = (out[0] if isinstance(out, list) and out else out) or {}
        pid = first.get("postId") or first.get("id") or (first.get("posts") or [{}])[0].get("id")
        if not pid:
            raise PostizError("Postiz accepted the post but didn't say its id")
        return str(pid)

    def status(self, post_id: str, around: datetime) -> dict:
        """The post's state (draft, queued, published, error), its public URL once live, and any error."""
        start, end = around - timedelta(days=2), around + timedelta(days=35)
        got = self._call("GET", "/posts", params={"startDate": start.isoformat(), "endDate": end.isoformat()})
        for p in (got.get("posts") if isinstance(got, dict) else got) or []:
            if str(p.get("id")) == post_id or str(p.get("group")) == post_id:
                raw = str(p.get("state") or p.get("status") or "").upper()
                state = {"PUBLISHED": "published", "ERROR": "error", "DRAFT": "draft", "QUEUE": "queued"}.get(raw, raw.lower() or "queued")
                return {"state": state, "url": p.get("releaseURL") or None, "error": p.get("error") or None}
        return {"state": "unknown", "url": None, "error": None}

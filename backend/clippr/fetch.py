"""Reading public posts and streams.

TikTok has no official API for watching accounts you don't own, so Vyral reads the same public
pages anyone can open, through yt-dlp: no login, no cookies, no CAPTCHA solving, slow polling
with backoff. If a platform blocks a check, Vyral waits and tries later instead of working
around it. Everything goes through the Fetcher interface so tests (and future official APIs)
can replace it.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol

from .media.ffmpeg import ffmpeg_exe


class FetchError(Exception):
    pass


@dataclass
class RemotePost:
    id: str
    url: str
    title: str = ""
    posted_at: datetime | None = None
    duration: float | None = None
    views: int | None = None
    likes: int | None = None
    comments: int | None = None
    shares: int | None = None
    thumbnail: str | None = None


@dataclass
class RemoteVod:
    id: str
    url: str
    title: str = ""
    duration: float | None = None
    published_at: datetime | None = None


class Fetcher(Protocol):
    def recent_posts(self, platform: str, username: str, profile_url: str, limit: int) -> list[RemotePost]: ...
    def post_details(self, url: str) -> RemotePost: ...
    def download_audio(self, url: str, dest_dir: Path) -> Path: ...
    def recent_vods(self, channel_url: str, limit: int) -> list[RemoteVod]: ...
    def vod_details(self, url: str) -> RemoteVod: ...
    def download_section(self, url: str, start: float, end: float, dest_dir: Path) -> Path: ...


MONITORABLE = ("tiktok", "youtube")

_SINGLE_VOD = re.compile(r"(twitch\.tv/videos/\d+|youtube\.com/watch\?|youtu\.be/|youtube\.com/live/)", re.I)


def is_single_video(url: str) -> bool:
    return bool(_SINGLE_VOD.search(url))


def channel_vod_listing(url: str) -> str:
    """Turn a channel link into the page that lists its past broadcasts."""
    u = url.strip().rstrip("/")
    m = re.match(r"^(?:https?://)?(?:www\.|m\.)?twitch\.tv/([A-Za-z0-9_]{3,25})(?:/.*)?$", u)
    if m:
        return f"https://www.twitch.tv/{m[1]}/videos?filter=archives&sort=time"
    m = re.match(r"^(?:https?://)?(?:www\.|m\.)?youtube\.com/((?:@[\w.\-]+)|(?:channel/[\w\-]+)|(?:c/[\w.\-]+))(?:/.*)?$", u)
    if m:
        return f"https://www.youtube.com/{m[1]}/streams"
    raise FetchError("Use a Twitch channel link (twitch.tv/name), a YouTube channel link (youtube.com/@name) or a single stream link")


def validate_stream_link(url: str) -> str:
    url = url.strip()
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    if is_single_video(url):
        return url
    channel_vod_listing(url)
    return url


def _ts(v) -> datetime | None:
    try:
        return datetime.fromtimestamp(int(v), tz=timezone.utc) if v else None
    except (TypeError, ValueError, OSError):
        return None


def _date(e: dict) -> datetime | None:
    """When the stream/video happened: exact timestamp if given, else the upload day."""
    for key in ("release_timestamp", "timestamp"):
        if e.get(key):
            return _ts(e[key])
    d = e.get("upload_date")
    if d and re.fullmatch(r"\d{8}", str(d)):
        return datetime(int(d[:4]), int(d[4:6]), int(d[6:8]), 12, tzinfo=timezone.utc)
    return None


def _post(e: dict, fallback_url: str = "") -> RemotePost:
    return RemotePost(
        id=str(e.get("id")), url=e.get("webpage_url") or e.get("url") or fallback_url, title=(e.get("title") or e.get("description") or "")[:2000],
        posted_at=_ts(e.get("timestamp")), duration=e.get("duration"), views=e.get("view_count"), likes=e.get("like_count"),
        comments=e.get("comment_count"), shares=e.get("repost_count"),
        thumbnail=e.get("thumbnail") or ((e.get("thumbnails") or [{}])[-1].get("url")),
    )


class YtDlpFetcher:
    def _opts(self, **extra) -> dict:
        return {"quiet": True, "no_warnings": True, "noprogress": True, "socket_timeout": 30, "retries": 3,
                "ffmpeg_location": ffmpeg_exe(), "noplaylist": False, "cachedir": False, **extra}

    def _extract(self, url: str, download: bool = False, **opts) -> dict:
        import yt_dlp

        try:
            with yt_dlp.YoutubeDL(self._opts(**opts)) as ydl:
                info = ydl.extract_info(url, download=download)
                return ydl.sanitize_info(info) if not download else info
        except yt_dlp.utils.DownloadError as e:
            msg = re.sub(r"\x1b\[[0-9;]*m", "", str(e)).replace("ERROR: ", "")
            raise FetchError(msg[:300])

    def recent_posts(self, platform: str, username: str, profile_url: str, limit: int) -> list[RemotePost]:
        if platform == "tiktok":
            url = f"https://www.tiktok.com/@{username}"
        elif platform == "youtube":
            url = profile_url.rstrip("/") + "/shorts"
        else:
            raise FetchError(f"Watching {platform} accounts isn't supported")
        info = self._extract(url, extract_flat="in_playlist", playlistend=limit)
        return [_post(e) for e in (info.get("entries") or [])[:limit] if e and e.get("id")]

    def post_details(self, url: str) -> RemotePost:
        return _post(self._extract(url, noplaylist=True), url)

    def download_audio(self, url: str, dest_dir: Path) -> Path:
        dest_dir.mkdir(parents=True, exist_ok=True)
        info = self._extract(url, download=True, noplaylist=True, format="bestaudio/best",
                             outtmpl=str(dest_dir / "%(id)s.%(ext)s"))
        return Path(info["requested_downloads"][0]["filepath"])

    def recent_vods(self, channel_url: str, limit: int) -> list[RemoteVod]:
        if is_single_video(channel_url):
            return [RemoteVod(id=channel_url, url=channel_url)]
        info = self._extract(channel_vod_listing(channel_url), extract_flat="in_playlist", playlistend=limit)
        out = []
        for e in (info.get("entries") or [])[:limit]:
            if e and e.get("id"):
                out.append(RemoteVod(str(e["id"]), e.get("url") or e.get("webpage_url"), e.get("title") or "", e.get("duration"), _date(e)))
        return out

    def vod_details(self, url: str) -> RemoteVod:
        e = self._extract(url, noplaylist=True)
        return RemoteVod(str(e.get("id")), url, e.get("title") or "", e.get("duration"), _date(e))

    def download_section(self, url: str, start: float, end: float, dest_dir: Path) -> Path:
        import yt_dlp

        dest_dir.mkdir(parents=True, exist_ok=True)
        # Best quality up to 1080p, and among those the highest frame rate (1080p60 over 1080p30).
        info = self._extract(url, download=True, noplaylist=True, format="bv*+ba/b", format_sort=["res:1080", "fps", "vbr"],
                             merge_output_format="mp4",
                             download_ranges=yt_dlp.utils.download_range_func(None, [(start, end)]),
                             outtmpl=str(dest_dir / "section-%(id)s.%(ext)s"))
        return Path(info["requested_downloads"][0]["filepath"])

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
    is_live: bool = False  # still being streamed: its audio can't be downloaded until it ends
    game: str = ""  # the category the stream was in (e.g. "Grand Theft Auto VI"), when the site says


class Fetcher(Protocol):
    def recent_posts(self, platform: str, username: str, profile_url: str, limit: int) -> list[RemotePost]: ...
    def post_details(self, url: str) -> RemotePost: ...
    def download_audio(self, url: str, dest_dir: Path) -> Path: ...
    def recent_vods(self, channel_url: str, limit: int) -> list[RemoteVod]: ...
    def vod_details(self, url: str) -> RemoteVod: ...
    def download_section(self, url: str, start: float, end: float, dest_dir: Path) -> Path: ...
    def twitch_clip_origin(self, url: str) -> tuple[str, float] | None: ...
    def download_post(self, url: str, dest_dir: Path) -> Path: ...
    def longform_details(self, url: str) -> tuple[str, float | None, list[dict] | None]: ...


MONITORABLE = ("tiktok", "youtube", "twitch", "kick")


def on_progress() -> None:
    """Replaced at startup with the job queue's beat(), so long downloads count as progress."""

# Single TikTok videos (full links and the short share links the app copies: vm./vt.tiktok.com/x and
# tiktok.com/t/x) and YouTube Shorts, found anywhere in pasted text.
_FIND_LINK = re.compile(r"https?://(?:(?:www\.|m\.)?tiktok\.com/(?:@[\w.-]+/video/\d+|t/\w+)|(?:vm|vt)\.tiktok\.com/\w+"
                        r"|(?:www\.|m\.)?youtube\.com/shorts/[\w-]+)/?(?:\?[^\s<>\"']*)?", re.I)


def _unglue(text: str) -> str:
    return re.sub(r"(?<!\s)(https?://)", r" \1", text)  # split links pasted back to back


def count_links(text: str) -> int:
    """Every link of any kind in pasted text."""
    return len(re.findall(r"https?://\S+", _unglue(text)))


def find_links(text: str) -> list[str]:
    """Every TikTok / YouTube Shorts video link in pasted text, in order, without repeats. Links can be glued
    together (a multi-line paste into a one-line box), wrapped in <> or followed by punctuation."""
    text = _unglue(text)
    out = []
    for m in _FIND_LINK.finditer(text):
        link = m.group(0).rstrip(".,;:!?)]}")
        link = "https://" + link.split("://", 1)[1]
        if link not in out:
            out.append(link)
    return out


_SINGLE_VOD = re.compile(r"(twitch\.tv/videos/\d+|youtube\.com/watch\?|youtu\.be/|youtube\.com/live/|kick\.com/video/[\w-]+|kick\.com/[\w-]+/videos/[\w-]+)", re.I)


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
    m = re.match(r"^(?:https?://)?(?:www\.)?kick\.com/([A-Za-z0-9_-]{2,40})(?:/.*)?$", u)
    if m and m[1].lower() not in ("video", "categories", "browse", "following"):
        return f"https://kick.com/{m[1]}/videos"
    raise FetchError("Use a Twitch (twitch.tv/name), YouTube (youtube.com/@name) or Kick (kick.com/name) channel link, or a single stream link")


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


# yt-dlp's messages for the usual account problems, reworded so a person knows what to do.
_FRIENDLY = [
    (re.compile(r"secondary user ID|universal data for rehydration", re.I),
     "TikTok didn't return this account's videos. Vyral tries again on the next check; if it keeps happening, make sure the account is public."),
    (re.compile(r"account is (likely )?(either )?private|videos are private", re.I), "This account or its videos are private, so Vyral can't see its posts."),
    (re.compile(r"does not have any videos", re.I), "This account hasn't posted any videos yet."),
]


def _friendly(message: str) -> str:
    msg = re.sub(r"\x1b\[[0-9;]*m", "", message).replace("ERROR: ", "")
    for pattern, text in _FRIENDLY:
        if pattern.search(msg):
            return text
    return re.sub(r"^\[[\w:]+\] [^:]+: ", "", msg)[:300]  # drop yt-dlp's "[tiktok:user] name: " prefix


def use_bundled_ffmpeg() -> None:
    """yt-dlp decides whether it can download part of a video (a stream section) without looking at the
    ffmpeg_location option; its own command line sets this instead. Without it, a computer with no system
    FFmpeg gets "ffmpeg is not installed" although Vyral ships one. Per thread, so call it before each use."""
    from yt_dlp.postprocessor.ffmpeg import FFmpegPostProcessor

    FFmpegPostProcessor._ffmpeg_location.set(ffmpeg_exe())


class YtDlpFetcher:
    def _opts(self, **extra) -> dict:
        return {"quiet": True, "no_warnings": True, "noprogress": True, "socket_timeout": 30, "retries": 3,
                "progress_hooks": [lambda _: on_progress()],  # a long download is progress too
                # FFmpeg downloads (stream sections) give up after 60 s without data instead of waiting forever.
                "external_downloader_args": {"ffmpeg_i": ["-rw_timeout", "60000000"]},
                "ffmpeg_location": ffmpeg_exe(), "noplaylist": False, "cachedir": False, **extra}

    def _extract(self, url: str, download: bool = False, **opts) -> dict:
        import yt_dlp

        use_bundled_ffmpeg()

        try:
            with yt_dlp.YoutubeDL(self._opts(**opts)) as ydl:
                info = ydl.extract_info(url, download=download)
                return ydl.sanitize_info(info) if not download else info
        except yt_dlp.utils.DownloadError as e:
            raise FetchError(_friendly(str(e)))

    def recent_posts(self, platform: str, username: str, profile_url: str, limit: int) -> list[RemotePost]:
        if platform == "tiktok":
            url = f"https://www.tiktok.com/@{username}"
        elif platform == "youtube":
            url = profile_url.rstrip("/") + "/shorts"
        elif platform == "twitch":
            url = f"https://www.twitch.tv/{username}/clips?filter=clips&range=24hr"  # the day's most-viewed clips first
        elif platform == "kick":
            url = f"https://kick.com/{username}/clips?sort=view&range=day"  # same for Kick
        else:
            raise FetchError(f"Watching {platform} accounts isn't supported")
        info = self._extract(url, extract_flat="in_playlist", playlistend=limit)
        return [_post(e) for e in (info.get("entries") or [])[:limit] if e and e.get("id")]

    def post_details(self, url: str) -> RemotePost:
        return _post(self._extract(url, noplaylist=True), url)

    def download_audio(self, url: str, dest_dir: Path) -> Path:
        dest_dir.mkdir(parents=True, exist_ok=True)
        # Only the sound is needed. Streams without an audio-only version (common on Kick) fall back to the
        # smallest video, not the full-quality one: same audio, a fraction of the download.
        info = self._extract(url, download=True, noplaylist=True, format="bestaudio/worst",
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

    def download_post(self, url: str, dest_dir: Path) -> Path:
        """A post itself (e.g. a viewer's Twitch or Kick clip) in its best quality."""
        dest_dir.mkdir(parents=True, exist_ok=True)
        info = self._extract(url, download=True, noplaylist=True, format="bv*+ba/b", format_sort=["res:1080", "fps"],
                             merge_output_format="mp4", outtmpl=str(dest_dir / "post-%(id)s.%(ext)s"))
        return Path(info["requested_downloads"][0]["filepath"])

    def longform_details(self, url: str) -> tuple[str, float | None, list[dict] | None]:
        """A long video's title, length and, on YouTube, its most-replayed graph (viewers rewinding)."""
        e = self._extract(url, noplaylist=True)
        return e.get("title") or "", e.get("duration"), e.get("heatmap")

    def twitch_clip_origin(self, url: str) -> tuple[str, float] | None:
        """The stream a Twitch clip was cut from and where in it the clip starts, as Twitch reports it publicly
        (the same anonymous web request yt-dlp makes for clips). None if the stream was deleted or isn't saved."""
        m = re.search(r"(?:clips\.twitch\.tv/(?:embed\?clip=)?|twitch\.tv/(?:\w+/)?clip/)([\w-]+)", url)
        if not m:
            return None
        import httpx
        client_id = "ue6666qo983tsx6so1t0vnawi233wa"  # Twitch's public web client, as yt-dlp uses
        try:  # follow yt-dlp if it ever changes it
            from yt_dlp.extractor.twitch import TwitchBaseIE
            client_id = TwitchBaseIE._CLIENT_ID.fget(type("C", (), {"_configuration_arg": lambda self, *a, **k: a[1]})())[0] or client_id
        except Exception:
            pass
        body = {"query": "query($slug: ID!) { clip(slug: $slug) { videoOffsetSeconds video { id } } }", "variables": {"slug": m[1]}}
        try:
            r = httpx.post("https://gql.twitch.tv/gql", json=body, headers={"Client-ID": client_id}, timeout=20)
            clip = ((r.json() or {}).get("data") or {}).get("clip") or {}
        except (httpx.HTTPError, ValueError):
            return None
        vid, offset = (clip.get("video") or {}).get("id"), clip.get("videoOffsetSeconds")
        if not vid or offset is None:
            return None
        return f"https://www.twitch.tv/videos/{vid}", float(offset)

    def vod_details(self, url: str) -> RemoteVod:
        e = self._extract(url, noplaylist=True)
        live = bool(e.get("is_live")) or e.get("live_status") == "is_live"
        game = (e.get("categories") or [""])[0] or e.get("category") or ""
        return RemoteVod(str(e.get("id")), url, e.get("title") or "", e.get("duration"), _date(e), live, str(game)[:80])

    def download_section(self, url: str, start: float, end: float, dest_dir: Path) -> Path:
        import yt_dlp

        dest_dir.mkdir(parents=True, exist_ok=True)
        # Best quality up to 1080p, and among those the highest frame rate (1080p60 over 1080p30).
        info = self._extract(url, download=True, noplaylist=True, format="bv*+ba/b", format_sort=["res:1080", "fps", "vbr"],
                             merge_output_format="mp4",
                             download_ranges=yt_dlp.utils.download_range_func(None, [(start, end)]),
                             outtmpl=str(dest_dir / "section-%(id)s.%(ext)s"))
        return Path(info["requested_downloads"][0]["filepath"])

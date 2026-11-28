"""Reading public posts and streams.

TikTok has no official API for watching accounts you don't own, so Vyral reads the same public
pages anyone can open, through yt-dlp: no login, no cookies, no CAPTCHA solving, slow polling
with backoff. If a platform blocks a check, Vyral waits and tries later instead of working
around it. Everything goes through the Fetcher interface so tests (and future official APIs)
can replace it.
"""
from __future__ import annotations

import json
import re
import shutil
import tempfile
import time
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
    channels: tuple[str, ...] = ()  # who posted it: handle, name, channel (any yt-dlp knows)
    music: str | None = None  # the song on it, as the platform names it (TikTok: "track - artist")


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
    def recent_uploads(self, profile_url: str, limit: int) -> list[RemotePost]: ...
    def post_details(self, url: str) -> RemotePost: ...
    def download_audio(self, url: str, dest_dir: Path) -> Path: ...
    def recent_vods(self, channel_url: str, limit: int) -> list[RemoteVod]: ...
    def vod_details(self, url: str) -> RemoteVod: ...
    def download_section(self, url: str, start: float, end: float, dest_dir: Path) -> Path: ...
    def twitch_clip_origin(self, url: str) -> tuple[str, float] | None: ...
    def download_post(self, url: str, dest_dir: Path) -> Path: ...
    def longform_details(self, url: str) -> tuple[str, float | None, list[dict] | None]: ...
    def chat_replay(self, url: str, windows: list[tuple[float, float]], budget: float) -> tuple[list[tuple[float, str]], list[tuple[float, float]]]: ...


MONITORABLE = ("tiktok", "youtube", "twitch", "kick")


def on_progress() -> None:
    """Replaced at startup with the job queue's beat(), so long downloads count as progress."""

# Single TikTok videos (full links and the short share links the app copies: vm./vt.tiktok.com/x and
# tiktok.com/t/x) and YouTube Shorts, found anywhere in pasted text.
_FIND_LINK = re.compile(r"https?://(?:(?:www\.|m\.)?tiktok\.com/(?:@[\w.-]+/video/\d+|t/\w+)|(?:vm|vt)\.tiktok\.com/\w+"
                        r"|(?:www\.|m\.)?youtube\.com/shorts/[\w-]+)/?(?:\?[^\s<>\"']*)?", re.I)


# A long video to break into clips: a YouTube video or live replay, or a Twitch or Kick past broadcast.
_LONG_LINK = re.compile(r"https?://(?:(?:www\.|m\.)?youtube\.com/(?:watch\?[^\s<>]*v=[\w-]+|live/[\w-]+)|youtu\.be/[\w-]+"
                        r"|(?:www\.)?twitch\.tv/videos/\d+|(?:www\.)?kick\.com/(?:video/[\w-]+|[\w-]+/videos/[\w-]+))[^\s<>]*", re.I)


def find_long_links(text: str) -> list[str]:
    """Links to long videos in pasted text, in order, without repeats."""
    out = []
    for m in _LONG_LINK.finditer(_unglue(text)):
        link = m.group(0).rstrip(".,;:!?)]}")
        if link not in out:
            out.append(link)
    return out


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
        channels=tuple(str(e[k]) for k in ("uploader_id", "uploader", "channel", "channel_id") if e.get(k)),
        music=" - ".join(str(e[k]) for k in ("track", "artist") if e.get(k)) or None,
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

    def recent_uploads(self, profile_url: str, limit: int) -> list[RemotePost]:
        """A YouTube channel's latest full videos and finished livestreams (not Shorts; not one that's live or
        scheduled right now: it's taken once it's over)."""
        out, seen = [], set()
        for tab in ("/videos", "/streams"):
            try:
                info = self._extract(profile_url.rstrip("/") + tab, extract_flat="in_playlist", playlistend=limit)
            except FetchError:
                continue  # a channel without streams has no Live tab
            for e in (info.get("entries") or [])[:limit]:
                if e and e.get("id") and e["id"] not in seen and e.get("live_status") not in ("is_live", "is_upcoming", "post_live"):
                    seen.add(e["id"])
                    out.append(_post(e, f"https://www.youtube.com/watch?v={e['id']}"))
        return out

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
        client_id = _twitch_client_id()
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

    def chat_replay(self, url: str, windows: list[tuple[float, float]], budget: float) -> tuple[list[tuple[float, str]], list[tuple[float, float]]]:
        """A past stream's chat, as read anonymously by anyone watching the replay: ([(seconds into the video, text)],
        [(from, to) stretches read]). Twitch: the windows asked for; YouTube: the live chat replay from the start (yt-dlp).
        Stops after `budget` seconds with what it has. Kick and others: nothing (([], []))."""
        deadline = time.monotonic() + budget
        m = re.search(r"twitch\.tv/videos/(\d+)", url)
        if m:
            return _twitch_chat(m[1], windows, deadline)
        if re.search(r"youtube\.com/(watch\?|live/)|youtu\.be/", url):
            return self._youtube_chat(url, deadline)
        return [], []

    def _youtube_chat(self, url: str, deadline: float) -> tuple[list[tuple[float, str]], list[tuple[float, float]]]:
        class OutOfTime(Exception):
            pass

        def hook(_):
            if time.monotonic() > deadline:
                raise OutOfTime  # keeps what was read so far (the .part file)

        work = Path(tempfile.mkdtemp(prefix="vyral-chat-"))
        done = False
        try:
            try:
                self._extract(url, download=True, noplaylist=True, skip_download=True, writesubtitles=True,
                              subtitleslangs=["live_chat"], ignore_no_formats_error=True, socket_timeout=15,
                              outtmpl=str(work / "chat"), progress_hooks=[hook])
                done = True
            except (OutOfTime, FetchError):
                pass
            msgs: list[tuple[float, str]] = []
            for f in work.glob("chat.live_chat.json*"):
                for line in f.read_text("utf-8", "replace").splitlines():
                    try:
                        msgs += _youtube_message(json.loads(line))
                    except (ValueError, TypeError, KeyError, AttributeError):
                        continue  # a half-written last line
        finally:
            shutil.rmtree(work, ignore_errors=True)
        last = max((t for t, _ in msgs), default=0.0)
        return msgs, ([(0.0, float("inf") if done else last)] if msgs else [])

    def download_section(self, url: str, start: float, end: float, dest_dir: Path) -> Path:
        import yt_dlp

        dest_dir.mkdir(parents=True, exist_ok=True)
        # Best quality up to 1080p, and among those the highest frame rate (1080p60 over 1080p30).
        info = self._extract(url, download=True, noplaylist=True, format="bv*+ba/b", format_sort=["res:1080", "fps", "vbr"],
                             merge_output_format="mp4",
                             download_ranges=yt_dlp.utils.download_range_func(None, [(start, end)]),
                             outtmpl=str(dest_dir / "section-%(id)s.%(ext)s"))
        return Path(info["requested_downloads"][0]["filepath"])


def _youtube_message(action: dict) -> list[tuple[float, str]]:
    """One line of yt-dlp's live_chat file: a replayed chat action with its time in the video."""
    replay = action.get("replayChatItemAction") or {}
    out = []
    for a in replay.get("actions") or []:
        r = (((a.get("addChatItemAction") or {}).get("item") or {}).get("liveChatTextMessageRenderer") or {})
        runs = (r.get("message") or {}).get("runs") or []
        text = " ".join(x.get("text") or ((x.get("emoji") or {}).get("shortcuts") or [""])[0].strip(":") for x in runs)
        if text.strip():
            out.append((int(replay["videoOffsetTimeMsec"]) / 1000, text))
    return out


TWITCH_PAUSE = 0.25  # at most four chat requests a second


def _twitch_chat(video_id: str, windows: list[tuple[float, float]], deadline: float) -> tuple[list[tuple[float, str]], list[tuple[float, float]]]:
    """Twitch's chat replay for each window, through the same anonymous public web request the Twitch player makes
    (no login). Stops at the deadline, or when Twitch says no or asks to slow down."""
    import httpx

    query = ("query($id: ID!, $t: Int, $c: Cursor) { video(id: $id) { comments(contentOffsetSeconds: $t, after: $c) {"
             " edges { cursor node { contentOffsetSeconds message { fragments { text } } } } pageInfo { hasNextPage } } } }")
    msgs: list[tuple[float, str]] = []
    covered: list[tuple[float, float]] = []
    with httpx.Client(timeout=10, headers={"Client-ID": _twitch_client_id()}) as client:
        for a, b in windows:
            variables, reached = {"id": video_id, "t": int(a)}, a
            while time.monotonic() < deadline:
                try:
                    r = client.post("https://gql.twitch.tv/gql", json={"query": query, "variables": variables})
                    r.raise_for_status()
                    page = (((r.json() or {}).get("data") or {}).get("video") or {}).get("comments") or {}
                except (httpx.HTTPError, ValueError, AttributeError):
                    if reached > a:
                        covered.append((a, reached))
                    return msgs, covered  # refused, rate limited or changed: keep what was read
                edges = page.get("edges") or []
                for e in edges:
                    n = e.get("node") or {}
                    t = float(n.get("contentOffsetSeconds") or 0)
                    msgs.append((t, "".join(f.get("text") or "" for f in (n.get("message") or {}).get("fragments") or [])))
                    reached = max(reached, t)
                if not edges or not (page.get("pageInfo") or {}).get("hasNextPage") or reached >= b:
                    reached = max(reached, b)
                    break
                variables = {"id": video_id, "c": edges[-1].get("cursor")}
                time.sleep(TWITCH_PAUSE)
            if reached > a:
                covered.append((a, min(reached, b)))
            time.sleep(TWITCH_PAUSE)
    return msgs, covered


def _twitch_client_id() -> str:
    """Twitch's public web client, as yt-dlp uses (and follows if it ever changes)."""
    try:
        from yt_dlp.extractor.twitch import TwitchBaseIE
        cid = TwitchBaseIE._CLIENT_ID.fget(type("C", (), {"_configuration_arg": lambda self, *a, **k: a[1]})())
        return cid if isinstance(cid, str) and cid else _TWITCH_WEB
    except Exception:
        return _TWITCH_WEB


_TWITCH_WEB = "ue6666qo983tsx6so1t0vnawi233wa"

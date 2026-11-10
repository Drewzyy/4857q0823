"""A stand-in for TikTok + Twitch that serves local files. Used by tests and the E2E test server."""
import shutil
from pathlib import Path

from datetime import datetime, timezone

from clippr.fetch import FetchError, RemotePost, RemoteVod
from clippr.media.overlay import Word
from clippr.media.transcribe import TranscribeError
from clippr.media.ffmpeg import run


class FakeFetcher:
    """Plays the part of TikTok + Twitch using local files."""

    def __init__(self, media):
        self.m = media
        self.posts: list[RemotePost] = []
        self.calls: list[tuple] = []
        self.fail_listing = False
        self.live: set[str] = set()  # stream urls that are still being broadcast
        self.origins: dict[str, tuple[str, float]] = {}
        self.heatmap: list[dict] | None = None  # Twitch clip url -> (its stream, offset)

    def recent_posts(self, platform, username, profile_url, limit):
        self.calls.append(("posts", username))
        if self.fail_listing:
            raise FetchError("HTTP Error 403: Forbidden")
        return self.posts[:limit]

    def post_details(self, url):
        return RemotePost(id=url.rsplit("/", 1)[-1], url=url, title="pasted clip #fyp")

    def _copy(self, src, dest_dir, name):
        dest_dir.mkdir(parents=True, exist_ok=True)
        out = dest_dir / name
        shutil.copyfile(src, out)
        return out

    def download_audio(self, url, dest_dir):
        self.calls.append(("audio", url))
        src = self.m["stream"] if url.endswith("/videos/2") or "watch?v=" in url else self.m["other"] if url.endswith("/videos/1") else self.m["clip"]
        return self._copy(src, dest_dir, Path(src).name)

    def recent_vods(self, channel_url, limit):
        self.calls.append(("vods", channel_url))
        return [RemoteVod("1", "https://www.twitch.tv/videos/1", "Yesterday's stream"),
                RemoteVod("2", "https://www.twitch.tv/videos/2", "Big stream")][:limit]

    def download_section(self, url, start, end, dest_dir):
        self.calls.append(("section", url, round(start, 1), round(end, 1)))
        dest_dir.mkdir(parents=True, exist_ok=True)
        out = dest_dir / "section.mp4"
        # Simulate a keyframe-aligned download that starts a bit earlier than asked.
        run(["-ss", f"{max(0, start - 1.7):.2f}", "-i", str(self.m["stream"]), "-t", f"{end - start + 1.7:.2f}",
             "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", str(out)])
        return out

    def longform_details(self, url):
        self.calls.append(("longform", url))
        return "A long stream", 240.0, self.heatmap

    def twitch_clip_origin(self, url):
        self.calls.append(("origin", url))
        return self.origins.get(url)

    def vod_details(self, url):
        self.calls.append(("vod_details", url))
        return RemoteVod(url.rsplit("/", 1)[-1], url, "Big stream", None, datetime(2026, 11, 7, 20, 0, tzinfo=timezone.utc), url in self.live)


class FakeTranscriber:
    """Stands in for the speech model (which needs a one-time internet download)."""

    def __init__(self, fail: bool = False):
        self.fail = fail
        self.calls = 0

    def words(self, audio, hints=()):
        self.calls += 1
        self.hints = list(hints)
        if self.fail:
            raise TranscribeError("Couldn't load the speech model (ConnectError). Check your internet connection for the one-time download.")
        text = "no way he actually did that right now".split()
        # Times are relative to the audio Vyral hands over, which starts 0.8 s before the clip.
        return [Word(1.2 + i * 0.45, 1.6 + i * 0.45, t) for i, t in enumerate(text)]


def drain(ctx):
    n = 0
    while ctx.jobs.run_one():
        n += 1
    return n

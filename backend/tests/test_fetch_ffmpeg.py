from yt_dlp.downloader.external import FFmpegFD
from yt_dlp.postprocessor.ffmpeg import FFmpegPostProcessor

from clippr.fetch import FetchError, YtDlpFetcher


def test_partial_downloads_use_the_bundled_ffmpeg(monkeypatch):
    """Like a Mac with no FFmpeg installed: yt-dlp must still find the one Vyral ships before cutting a section."""
    monkeypatch.setenv("PATH", "")
    FFmpegPostProcessor._ffmpeg_location.set(None)
    assert not FFmpegFD.available()  # the bug: yt-dlp's check ignores the ffmpeg_location option
    try:
        YtDlpFetcher()._extract("https://invalid.invalid/x", process=False)
    except FetchError:
        pass  # no network needed; only the setup before the request matters
    assert FFmpegFD.available()

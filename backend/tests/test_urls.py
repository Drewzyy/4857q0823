import pytest

from clippr.platforms.urls import SourceInputError, parse_source_input as p


@pytest.mark.parametrize("text,platform,user", [
    ("streamerclips", "tiktok", "streamerclips"),
    ("@StreamerClips", "tiktok", "streamerclips"),
    ("https://www.tiktok.com/@kai.clips", "tiktok", "kai.clips"),
    ("tiktok.com/@kai_clips/video/7300000000000000000", "tiktok", "kai_clips"),
    ("https://m.tiktok.com/@abc123?lang=en", "tiktok", "abc123"),
    ("https://www.youtube.com/@SomeStreamer", "youtube", "@SomeStreamer".lstrip("@")),
    ("https://youtube.com/channel/UC1234567890123456789012", "youtube", "UC1234567890123456789012"),
    ("https://www.twitch.tv/SomeStreamer", "twitch", "somestreamer"),
    ("instagram.com/some.page/", "instagram", "some.page"),
])
def test_parse_ok(text, platform, user):
    r = p(text)
    assert (r.platform, r.username) == (platform, user)
    assert r.profile_url.startswith("https://")


@pytest.mark.parametrize("text", [
    "", "https://vm.tiktok.com/ZMabc/", "https://evil.com/@x", "javascript:alert(1)", "bad name!",
    "https://www.youtube.com/watch?v=abc", "https://www.tiktok.com/foryou", "x" * 400,
])
def test_parse_rejects(text):
    with pytest.raises(SourceInputError):
        p(text)

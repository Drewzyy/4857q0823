from clippr.fetch import _friendly


def test_ytdlp_errors_read_like_sentences():
    assert _friendly("ERROR: [tiktok:user] im_goochy: Unable to extract secondary user ID. If you are able").startswith("TikTok didn't return")
    assert "private" in _friendly("ERROR: [tiktok:user] x: This user's account is private. Log into an account that has access")
    assert _friendly("\x1b[0;31mERROR:\x1b[0m [twitch:vod] 123: Video does not exist") == "Video does not exist"

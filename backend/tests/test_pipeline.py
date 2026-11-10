"""The automatic loop end to end: real audio matching, real FFmpeg renders, simulated internet."""
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest
import respx

from clippr.fetch import RemotePost
from clippr.media.ffmpeg import probe
from clippr.models import Clip, ClipOutput
from fakes import FakeTranscriber, drain

HOOK = "https://discord.com/api/webhooks/123456789/abcdefghijklmnopqrstuvwxyz_123"
TOKEN = "test-token"


def _frame(path, t):
    import numpy as np
    from clippr.media.ffmpeg import ffmpeg_exe
    import subprocess
    raw = subprocess.run([ffmpeg_exe(), "-v", "error", "-ss", str(t), "-i", str(path), "-frames:v", "1", "-f", "rawvideo", "-pix_fmt", "rgb24", "-"],
                         capture_output=True, check=True).stdout
    info = probe(path)
    return np.frombuffer(raw, np.uint8).reshape(info.height, info.width, 3).astype(int)


def yellow_pixels(path, t, top):
    f = _frame(path, t)
    h = f.shape[0]
    region = f[: int(h * 0.25)] if top else f[int(h * 0.6): int(h * 0.8)]
    r, g, b = region[..., 0], region[..., 1], region[..., 2]
    return int(((r > 235) & (g > 210) & (b < 60)).sum())


def white_pixels(path, t):
    f = _frame(path, t)
    region = f[: int(f.shape[0] * 0.25)]
    return int(((region > 240).all(axis=2)).sum())


def setup_accounts(c, *, permission=True, channels=("https://www.twitch.tv/streamera",)):
    cr = c.post("/api/creators", json={"name": "Streamer A", "clip_permission": permission, "vod_channels": list(channels)})
    assert cr.status_code == 201, cr.text
    cid = cr.json()["id"]
    sid = c.post("/api/sources", json={"input": "@a.clips", "creator_id": cid}).json()["id"]
    tt = c.post("/api/destinations", json={"platform": "tiktok", "display_name": "Streamer A TikTok", "handle": "streamera.tt", "creator_id": cid}).json()
    c.patch(f"/api/destinations/{tt['id']}", json={"settings": {"hashtags": ["gaming", "#clips"], "default_caption": "Follow for more"}})
    yt = c.post("/api/destinations", json={"platform": "youtube", "display_name": "Streamer A YouTube", "handle": "@streameraYT", "creator_id": cid}).json()
    c.patch(f"/api/destinations/{yt['id']}", json={"settings": {"format": {"aspect": "9:16", "resolution": "720x1280", "fps": 30}}})
    assert c.post("/api/funnel/auto-route", json={}).json()["created"] == 2
    return cid, sid, tt["id"], yt["id"]


@respx.mock
def test_new_post_becomes_ready_to_upload_clip(env):
    ctx, c, fake = env
    discord = respx.post(HOOK).mock(return_value=httpx.Response(204))
    assert c.put("/api/notifications", json={"webhook_url": HOOK}).json()["configured"] is True
    _, sid, *_ = setup_accounts(c)

    # First check records what's already there and makes nothing.
    fake.posts = [RemotePost("old1", "https://www.tiktok.com/@a.clips/video/old1", "old one")]
    assert ctx.pipeline.check_source(sid)["baseline"] is True
    assert drain(ctx) == 0 and not discord.called
    assert c.get("/api/references").json() == []

    # A new post appears: Discord ping, then the clip gets built automatically.
    fake.posts = [RemotePost("new1", "https://www.tiktok.com/@a.clips/video/new1", "He actually did it 😭 #fyp @someone",
                             thumbnail="https://p.example/t.jpg"), *fake.posts]
    assert ctx.pipeline.check_source(sid)["new"] == 1
    drain(ctx)

    ref = c.get("/api/references").json()[0]
    assert ref["status"] == "ready", ref
    assert ref["vod_url"].endswith("/videos/2") and abs(ref["vod_start"] - 130.5) < 1.0 and ref["match_confidence"] > 0.5

    clips = c.get("/api/clips").json()
    assert len(clips) == 1 and len(clips[0]["outputs"]) == 2
    outs = {o["platform"]: o for o in clips[0]["outputs"]}
    assert outs["tiktok"]["width"] == 1080 and outs["tiktok"]["height"] == 1920
    assert outs["youtube"]["width"] == 720 and outs["youtube"]["height"] == 1280
    tdesc = outs["tiktok"]["description"]
    local = datetime(2026, 11, 7, 20, tzinfo=timezone.utc).astimezone()
    assert tdesc == (f"He actually did it 😭\n\nFollow for more\n\nStreamer: Streamer A\nStreamed {local:%b} {local.day}, {local.year}"
                     "\n\n#fyp #gaming #clips #vyralclips"), tdesc
    assert "@someone" not in tdesc
    assert outs["youtube"]["title"] == "He actually did it 😭"
    assert outs["youtube"]["description"].endswith("#fyp #vyralclips #shorts")

    # Text on the video: ALL CAPS bold, white title at the top for 5 s, yellow captions from speech.
    tt_out = outs["tiktok"]
    assert tt_out["video_title"] == "He actually did it 😭"
    assert tt_out["overlay"]["title"]["color"] == "#FFFFFF" and tt_out["overlay"]["captions"]["color"] == "#FFE500"
    assert tt_out["overlay"]["title"]["all_caps"] and tt_out["overlay"]["title"]["duration"] == 5
    assert clips[0]["captions_text"] == "no way he actually did that right now" and clips[0]["editable"]
    assert outs["tiktok"]["destination"]["handle"] == "@streamera.tt"

    # Rendered from the original stream, cut to the moment (20 s clip + 3 s jump cut + padding).
    with ctx.db.session() as s:
        path = Path(s.get(ClipOutput, outs["tiktok"]["id"]).file_path)
    info = probe(path)
    assert 22.5 < info.duration < 25.5 and info.has_audio
    # The white title is really burned in at the top during the first seconds, and gone after 5 s.
    assert white_pixels(path, 2.0) > 2000
    assert white_pixels(path, 7.0) < 50
    assert yellow_pixels(path, 1.2, top=False) > 2000  # yellow caption "NO WAY HE" in the lower part
    assert info.fps == 30  # the stream is 30 fps; never padded with fake frames

    # Discord got "new post" then "ready" with both platforms.
    msgs = [httpx.Request("POST", HOOK, content=call.request.content) for call in discord.calls]
    bodies = [call.request.content.decode() for call in discord.calls]
    assert len(msgs) == 2 and "a.clips" in bodies[0] and "just posted" in bodies[0]
    assert "Clip ready for upload" in bodies[1] and "TikTok" in bodies[1] and "YouTube" in bodies[1] and "@streamera.tt" in bodies[1]

    # Edit the burned-in title + style for one page and re-render it.
    old_file = path
    r = c.patch(f"/api/outputs/{tt_out['id']}/video", json={"video_title": "NEW TITLE", "overlay": {"title": {"color": "#FFE500", "size": 90}}})
    assert r.status_code == 200 and r.json()["render_state"] == "rendering"
    assert c.post(f"/api/outputs/{tt_out['id']}/save").status_code == 409  # not mid-render
    drain(ctx)
    o2 = next(o for o in c.get("/api/clips").json()[0]["outputs"] if o["id"] == tt_out["id"])
    assert o2["render_state"] == "ready" and o2["video_title"] == "NEW TITLE" and o2["overlay"]["title"]["color"] == "#FFE500"
    assert o2["version"] != tt_out["version"] and not old_file.exists()
    with ctx.db.session() as s:
        path = Path(s.get(ClipOutput, tt_out["id"]).file_path)
    assert white_pixels(path, 2.0) < 50 and yellow_pixels(path, 2.0, top=True) > 2000
    assert c.patch(f"/api/outputs/{tt_out['id']}/video", json={"overlay": {"title": {"color": "red"}}}).status_code == 422

    # Fix a misheard word: timing is kept, every page re-renders.
    r = c.patch(f"/api/clips/{clips[0]['id']}/captions", json={"text": "no way he ACTUALLY did that right now bro"})
    assert r.json()["rendering"] == 2
    drain(ctx)
    with ctx.db.session() as s:
        words = s.get(Clip, clips[0]["id"]).words
    assert [w["text"] for w in words][3] == "ACTUALLY" and words[3]["start"] == pytest.approx(0.4 + 3 * 0.45)
    assert words[-1]["text"] == "bro"

    # Preview stream works with the token in the query (for <video src>), not without.
    oid = outs["tiktok"]["id"]
    assert c.get(f"/api/media/outputs/{oid}", headers={"X-Clippr-Token": ""}, params={"t": TOKEN}).status_code == 200
    assert c.get(f"/api/media/outputs/{oid}", headers={"X-Clippr-Token": ""}).status_code == 401

    # Save to Downloads, edit caption, mark uploaded.
    with ctx.db.session() as s:
        path = Path(s.get(ClipOutput, oid).file_path)  # replaced by the re-renders above
    saved = Path(c.post(f"/api/outputs/{oid}/save").json()["path"])
    assert saved.exists() and saved.parent.name == "Vyral" and saved.stat().st_size == path.stat().st_size
    assert c.patch(f"/api/outputs/{oid}", json={"description": "edited"}).json()["description"] == "edited"
    assert c.patch(f"/api/outputs/{oid}", json={"status": "uploaded"}).json()["status"] == "uploaded"
    assert len(c.get("/api/clips", params={"status": "uploaded"}).json()) == 1

    # The stream's audio features are cached, so the next post doesn't re-download the stream.
    fake.calls.clear()
    fake.posts = [RemotePost("new2", "https://www.tiktok.com/@a.clips/video/new2", "again"), *fake.posts]
    ctx.pipeline.check_source(sid)
    drain(ctx)
    assert ("audio", "https://www.twitch.tv/videos/2") not in fake.calls

    # After the retention period the videos are deleted automatically.
    with ctx.db.session() as s:
        for clip in s.query(Clip).all():
            clip.expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
    assert ctx.pipeline.cleanup()["clips_expired"] == 2
    assert not path.exists()
    assert c.get("/api/clips", params={"status": "expired"}).json()[0]["outputs"][0]["available"] is False
    assert c.post(f"/api/outputs/{oid}/save").status_code == 410


@respx.mock
def test_problems_are_explained_and_pinged(env):
    ctx, c, fake = env
    discord = respx.post(HOOK).mock(return_value=httpx.Response(204))
    c.put("/api/notifications", json={"webhook_url": HOOK, "on_new_post": False})
    cid, sid, *_ = setup_accounts(c, permission=False)
    fake.posts = []
    ctx.pipeline.check_source(sid)
    fake.posts = [RemotePost("p1", "https://www.tiktok.com/@a.clips/video/p1", "x")]
    ctx.pipeline.check_source(sid)
    drain(ctx)
    ref = c.get("/api/references").json()[0]
    assert ref["status"] == "needs_setup" and "permission" in ref["status_detail"]
    assert len(discord.calls) == 1 and "couldn't make a clip" in discord.calls[0].request.content.decode()

    # Fix it, but the moment isn't in the searched streams.
    c.patch(f"/api/creators/{cid}", json={"clip_permission": True})
    fake.m = {"clip": fake.m["other"], "stream": fake.m["clip"], "other": fake.m["clip"]}  # post audio is in neither stream
    c.post(f"/api/references/{ref['id']}/retry", json={})
    drain(ctx)
    ref = c.get("/api/references").json()[0]
    assert ref["status"] == "no_match" and "Couldn't find this moment" in ref["status_detail"]


def test_monitoring_backoff_and_scheduling(env):
    ctx, c, fake = env
    _, sid, *_ = setup_accounts(c)
    assert c.post("/api/sources", json={"input": "https://www.instagram.com/somepage"}).status_code == 201  # not watchable, must be skipped
    assert ctx.pipeline.tick()["queued"] == 1
    assert ctx.pipeline.tick()["queued"] == 0  # not due again yet
    fake.fail_listing = True
    drain(ctx)
    src = next(x for x in c.get("/api/sources").json() if x["id"] == sid)
    assert "Couldn't check" in src["last_error"]
    assert datetime.fromisoformat(src["next_check_at"]) > datetime.now(timezone.utc) + timedelta(minutes=15)
    assert c.post(f"/api/sources/{sid}/check").status_code == 200
    insta = next(x for x in c.get("/api/sources").json() if x["platform"] == "instagram")
    assert c.post(f"/api/sources/{insta['id']}/check").status_code == 422
    c.put("/api/settings", json={"monitoring": {"enabled": False}})
    assert ctx.pipeline.tick() == {"monitoring": "off"}


def test_creator_links_and_webhook_validation(env):
    _ctx, c, _ = env
    r = c.post("/api/creators", json={"name": "X", "vod_channels": ["twitch.tv/xqc", "https://www.youtube.com/@Someone/videos", "https://evil.com/a"]})
    assert r.status_code == 422 and "evil.com" in r.json()["error"]["message"]
    r = c.post("/api/creators", json={"name": "X", "vod_channels": ["twitch.tv/xqc", "https://www.youtube.com/@Someone/videos", "kick.com/xqc",
                                                                   "https://kick.com/xqc/videos/0a1b2c3d-1111-2222-3333-444455556666"]})
    assert r.json()["vod_channels"] == ["https://twitch.tv/xqc", "https://www.youtube.com/@Someone/videos", "https://kick.com/xqc",
                                        "https://kick.com/xqc/videos/0a1b2c3d-1111-2222-3333-444455556666"]
    from clippr.fetch import channel_vod_listing, is_single_video
    assert channel_vod_listing("https://kick.com/xqc") == "https://kick.com/xqc/videos"
    assert channel_vod_listing("youtube.com/@Someone") == "https://www.youtube.com/@Someone/streams"
    assert is_single_video("https://kick.com/xqc/videos/0a1b2c3d-1111-2222-3333-444455556666")
    for bad in ["https://example.com/api/webhooks/1/x", "http://discord.com/api/webhooks/123456/abcdefghijklmnopqrstuvwxyz", "not a url"]:
        assert c.put("/api/notifications", json={"webhook_url": bad}).status_code == 422
    assert c.post("/api/notifications/test").status_code == 409
    assert c.get("/api/notifications").json()["configured"] is False


def test_captions_skipped_gracefully_without_speech_model(env):
    ctx, c, fake = env
    ctx.transcriber = FakeTranscriber(fail=True)
    _, sid, *_ = setup_accounts(c)
    fake.posts = []
    ctx.pipeline.check_source(sid)
    fake.posts = [RemotePost("q1", "https://www.tiktok.com/@a.clips/video/q1", "quiet one")]
    ctx.pipeline.check_source(sid)
    drain(ctx)
    clip = c.get("/api/clips").json()[0]
    assert clip["has_captions"] is False and "Captions skipped" in clip["captions_note"]
    assert c.get("/api/references").json()[0]["status"] == "ready"


def test_one_clipping_account_covering_several_streamers(env):
    """@a.clips clips Streamer A and Streamer B. A post is found in B's stream, so only B's pages get it."""
    ctx, c, fake = env
    a = c.post("/api/creators", json={"name": "Streamer A", "clip_permission": True, "vod_channels": ["https://www.twitch.tv/streamera"]}).json()["id"]
    b = c.post("/api/creators", json={"name": "Streamer B", "clip_permission": True, "vod_channels": ["https://kick.com/streamerb"]}).json()["id"]
    src = c.post("/api/sources", json={"input": "@general.clips", "creator_ids": [a, b]}).json()
    assert [x["name"] for x in src["creators"]] == ["Streamer A", "Streamer B"]
    c.post("/api/destinations", json={"platform": "tiktok", "display_name": "A page", "creator_id": a})
    c.post("/api/destinations", json={"platform": "tiktok", "display_name": "B page", "creator_id": b})
    assert c.post("/api/funnel/auto-route", json={}).json()["created"] == 2  # one account feeds both streamers' pages
    assert len(c.get("/api/sources", params={"creator_id": b}).json()) == 1
    # Streamer A's channel listing has no match; Streamer B's (Kick) does.
    orig = fake.recent_vods
    fake.recent_vods = lambda ch, limit: [] if "twitch" in ch else orig(ch, limit)
    fake.posts = []
    ctx.pipeline.check_source(src["id"])
    fake.posts = [RemotePost("m1", "https://www.tiktok.com/@general.clips/video/m1", "wild moment #fyp")]
    ctx.pipeline.check_source(src["id"])
    drain(ctx)
    ref = c.get("/api/references").json()[0]
    assert ref["status"] == "ready" and ref["creator"]["name"] == "Streamer B", ref["status_detail"]
    outs = c.get("/api/clips").json()[0]["outputs"]
    assert [o["destination"]["display_name"] for o in outs] == ["B page"]
    assert "Streamer: Streamer B" in outs[0]["description"]
    # Removing one streamer keeps the other.
    r = c.patch(f"/api/sources/{src['id']}", json={"creator_ids": [b]}).json()
    assert [x["name"] for x in r["creators"]] == ["Streamer B"]


def test_analytics_from_post_links(env):
    ctx, c, fake = env
    _, sid, *_ = setup_accounts(c)
    fake.posts = []
    ctx.pipeline.check_source(sid)
    fake.posts = [RemotePost("an1", "https://www.tiktok.com/@a.clips/video/an1", "big moment")]
    ctx.pipeline.check_source(sid)
    drain(ctx)
    outs = {o["platform"]: o for o in c.get("/api/clips").json()[0]["outputs"]}
    # Nothing uploaded yet: numbers are unavailable, not zero.
    a = c.get("/api/analytics").json()
    assert a["uploaded"] == 0 and a["totals"]["views"] is None and a["clips_made"] == 1
    assert c.put(f"/api/outputs/{outs['tiktok']['id']}/post", json={"post_url": "https://www.youtube.com/shorts/x"}).status_code == 422
    fake.post_details = lambda url: RemotePost("p", url, "t", views=12000, likes=900, comments=40, shares=60)
    r = c.put(f"/api/outputs/{outs['tiktok']['id']}/post", json={"post_url": "https://www.tiktok.com/@streamera.tt/video/999"})
    assert r.json()["auto"] is True
    drain(ctx)  # reads the post's public numbers
    c.put(f"/api/outputs/{outs['youtube']['id']}/post", json={"post_url": "https://youtube.com/shorts/abc"})
    fake.post_details = lambda url: RemotePost("p", url, "t", views=3000, likes=100)
    drain(ctx)
    a = c.get("/api/analytics").json()
    assert a["uploaded"] == 2 and a["tracked"] == 2
    assert a["totals"]["views"] == 15000 and a["totals"]["likes"] == 1000
    assert a["by_platform"][0]["key"] == "tiktok" and a["by_platform"][0]["views"] == 12000
    assert a["by_creator"][0]["label"] == "Streamer A" and a["top"][0]["views"] == 12000
    assert a["by_length"][0]["label"] == "20 to 40 s"
    assert c.get("/api/analytics", params={"platform": "youtube"}).json()["totals"]["views"] == 3000
    # Manual numbers for a platform Vyral can't read.
    assert c.post(f"/api/outputs/{outs['tiktok']['id']}/metrics", json={}).status_code == 422
    c.post(f"/api/outputs/{outs['tiktok']['id']}/metrics", json={"views": 20000})
    assert c.get("/api/analytics").json()["totals"]["views"] == 23000
    assert ctx.pipeline.refresh_metrics()["queued"] == 2


def test_video_editor_trim_zoom_speed_and_text(env):
    ctx, c, fake = env
    _, sid, *_ = setup_accounts(c)
    fake.posts = []
    ctx.pipeline.check_source(sid)
    fake.posts = [RemotePost("ed1", "https://www.tiktok.com/@a.clips/video/ed1", "edit me")]
    ctx.pipeline.check_source(sid)
    drain(ctx)
    clip = c.get("/api/clips").json()[0]
    ed = c.get(f"/api/clips/{clip['id']}/editor").json()
    e = ed["edit"]
    assert e["zoom"] == 1 and e["speed"] == 1 and ed["section_duration"] > e["end"] - e["start"]
    assert c.get(f"/api/media/clips/{clip['id']}/source", headers={"X-Clippr-Token": ""}, params={"t": TOKEN}).status_code == 200
    # Trim 4 s off the end, zoom in, speed up 1.25x, add a text from 1 s to 3 s.
    new = {**e, "end": e["end"] - 4, "zoom": 1.5, "pan_x": 0.3, "speed": 1.25,
           "texts": [{"text": "WAIT FOR IT", "start": 1, "end": 3, "y_percent": 40, "size": 90, "color": "#22C55E", "font": "anton", "all_caps": True, "outline": 6}]}
    assert c.put(f"/api/clips/{clip['id']}/edit", json={**new, "end": e["start"] + 0.5}).status_code == 422
    assert c.put(f"/api/clips/{clip['id']}/edit", json={**new, "zoom": 5}).status_code == 422
    backwards = {**new["texts"][0], "start": 3, "end": 1}
    assert c.put(f"/api/clips/{clip['id']}/edit", json={**new, "texts": [backwards]}).status_code == 422
    assert c.put(f"/api/clips/{clip['id']}/edit", json=new).json()["rendering"] == 2
    drain(ctx)
    outs = c.get("/api/clips").json()[0]["outputs"]
    assert all(o["render_state"] == "ready" for o in outs)
    with ctx.db.session() as s:
        path = Path(s.get(ClipOutput, outs[0]["id"]).file_path)
    info = probe(path)
    expect = (new["end"] - new["start"]) / 1.25
    assert abs(info.duration - expect) < 0.4, (info.duration, expect)
    f = _frame(path, 2.0)  # the green text is burned in during its window
    g = ((f[..., 1] > 170) & (f[..., 0] < 90) & (f[..., 2] < 120)).sum()
    assert g > 1500
    assert c.get(f"/api/clips/{clip['id']}/editor").json()["edit"]["zoom"] == 1.5


def test_posts_made_while_checks_failed_are_still_clipped(env):
    ctx, c, fake = env
    _, sid, *_ = setup_accounts(c)
    fake.fail_listing = True
    assert "error" in ctx.pipeline.check_source(sid)
    fake.fail_listing = False
    before = RemotePost("pre", "https://www.tiktok.com/@a.clips/video/pre", "older", posted_at=datetime(2020, 1, 1, tzinfo=timezone.utc))
    after = RemotePost("post", "https://www.tiktok.com/@a.clips/video/post", "posted after watching started",
                       posted_at=datetime.now(timezone.utc) + timedelta(seconds=5))
    fake.posts = [after, before]
    res = ctx.pipeline.check_source(sid)
    assert res["baseline"] is True and res["new"] == 1
    drain(ctx)
    refs = {r["url"].rsplit("/", 1)[-1]: r["status"] for r in c.get("/api/references").json()}
    assert refs == {"post": "ready"}  # the older post is skipped (skipped posts aren't listed)


def test_pasted_link_finds_the_streamer_it_names(env):
    """A pasted link has no source account: Vyral searches every streamer, the one the caption names first,
    and the clip goes only to that streamer's pages."""
    ctx, c, fake = env
    a = c.post("/api/creators", json={"name": "Streamer A", "clip_permission": True, "vod_channels": ["https://www.twitch.tv/streamera"]}).json()["id"]
    b = c.post("/api/creators", json={"name": "Streamer B", "clip_permission": True, "vod_channels": ["https://kick.com/streamerb"]}).json()["id"]
    c.post("/api/destinations", json={"platform": "tiktok", "display_name": "A page", "creator_id": a})
    c.post("/api/destinations", json={"platform": "tiktok", "display_name": "B page", "creator_id": b})
    # Both streamers were in the same moment (both streams have it), so the caption decides whose cut it is.
    fake.post_details = lambda url: RemotePost("p9", url, "streamer b did NOT just say that #streamerb #fyp")
    assert c.post("/api/references", json={"url": "https://www.tiktok.com/@someone/video/p9"}).status_code in (200, 201)
    drain(ctx)
    ref = c.get("/api/references").json()[0]
    assert ref["status"] == "ready" and ref["creator"]["name"] == "Streamer B", ref["status_detail"]
    assert [o["destination"]["display_name"] for o in c.get("/api/clips").json()[0]["outputs"]] == ["B page"]
    # Streamer B's streams are searched before Streamer A's.
    order = ctx.pipeline._search_order([(a, "Streamer A", ["https://www.twitch.tv/streamera"]), (b, "Streamer B", ["https://kick.com/streamerb"])],
                                       "streamer b did NOT just say that #streamerb #fyp", None, 2)
    assert [cname for _, _, cname in order] == ["Streamer B", "Streamer B", "Streamer A", "Streamer A"]


def test_twitch_channel_clips_become_videos(env):
    """A streamer's Twitch channel as a source: its most-watched new clips are matched to the VOD and rendered;
    clips few people watched wait, and a second clip of the same moment isn't made twice."""
    ctx, c, fake = env
    cid = c.post("/api/creators", json={"name": "Streamer A", "clip_permission": True, "vod_channels": ["https://www.twitch.tv/streamera"]}).json()["id"]
    src = c.post("/api/sources", json={"input": "twitch.tv/streamera", "platform": "twitch", "creator_ids": [cid]})
    assert src.status_code == 201, src.text
    sid = src.json()["id"]
    assert src.json()["watching_supported"] is True
    c.post("/api/destinations", json={"platform": "tiktok", "display_name": "A page", "creator_id": cid})
    c.post("/api/funnel/auto-route", json={})
    soon = datetime.now(timezone.utc) + timedelta(seconds=5)
    clip = lambda i, views: RemotePost(i, f"https://www.twitch.tv/streamera/clip/{i}", f"clip {i}", posted_at=soon, views=views)
    fake.posts = [clip("Top1", 900), clip("Top2", 400), clip("Quiet", 3)]  # most-viewed first, like Twitch's list
    res = ctx.pipeline.check_source(sid)
    assert res["new"] == 2  # the quiet clip isn't taken yet
    drain(ctx)
    refs = {r["url"].rsplit("/", 1)[-1]: r["status"] for r in c.get("/api/references").json()}
    assert refs == {"Top1": "ready", "Top2": "duplicate"}  # both clips are the same moment in the stream
    assert len(c.get("/api/clips").json()) == 1
    # Once enough people watch the quiet clip, it's picked up on a later check.
    fake.posts = [clip("Quiet", 120)]
    assert ctx.pipeline.check_source(sid)["new"] == 1


def test_a_render_overtaken_by_a_newer_edit_is_dropped(env):
    """Two re-renders of one video can overlap; the one started before the latest edit must not win."""
    ctx, c, fake = env
    _, sid, *_ = setup_accounts(c)
    fake.posts = []
    ctx.pipeline.check_source(sid)
    fake.posts = [RemotePost("r1", "https://www.tiktok.com/@a.clips/video/r1", "race")]
    ctx.pipeline.check_source(sid)
    drain(ctx)
    oid = c.get("/api/clips").json()[0]["outputs"][0]["id"]
    real_render = ctx.pipeline._render

    def render_then_edit(*a, **k):  # the user saves a new title while this render is still running
        out = real_render(*a, **k)
        with ctx.db.session() as s:
            s.get(ClipOutput, oid).video_title = "NEWER TITLE"
        return out

    ctx.pipeline._render = render_then_edit
    before = c.get("/api/clips").json()[0]["outputs"][0]["version"]
    assert ctx.pipeline.rerender([oid]) == {"rendered": 0}
    out = c.get("/api/clips").json()[0]["outputs"][0]
    assert out["version"] == before  # the stale render was thrown away, not saved over the video


def test_copied_and_batch_pasted_links_become_clips_once(env):
    ctx, c, fake = env
    setup_accounts(c)
    link = "https://www.tiktok.com/@someclipper/video/7351234567890"
    fake.post_details = lambda url: RemotePost(url.rsplit("/", 1)[-1], url, "he did NOT #streamera")
    r = c.post("/api/intake", json={"urls": [link, link, "https://www.tiktok.com/@someclipper", "my notes"], "from_clipboard": True}).json()
    assert r == {"queued": 1, "ignored": 3}  # one video link; a profile link and other text are ignored
    drain(ctx)
    assert [x["status"] for x in c.get("/api/references").json()] == ["ready"]
    # Copying it again later doesn't make it twice.
    assert c.post("/api/intake", json={"urls": [link], "from_clipboard": True}).json()["queued"] == 1
    drain(ctx)
    assert len(c.get("/api/clips").json()) == 1
    # Clipboard pickup can be switched off; batch paste still works.
    c.put("/api/settings", json={"intake": {"clipboard": False}})
    assert c.post("/api/intake", json={"urls": [link], "from_clipboard": True}).json()["queued"] == 0
    assert c.post("/api/intake", json={"urls": ["https://vm.tiktok.com/ZMabc123/", "https://www.youtube.com/shorts/xyz_1"]}).json()["queued"] == 2


def test_group_page_gets_clips_from_each_members_account(env):
    """Each member is their own streamer, and every member's account is routed to one group page tied to the group:
    the routes are respected (this used to stop with "isn't routed to any page")."""
    ctx, c, fake = env
    core = c.post("/api/creators", json={"name": "The Core", "clip_permission": True, "vod_channels": ["https://www.twitch.tv/silky"]}).json()["id"]
    silky = c.post("/api/creators", json={"name": "Silky", "clip_permission": True, "vod_channels": ["https://www.twitch.tv/silky"]}).json()["id"]
    page = c.post("/api/destinations", json={"platform": "tiktok", "display_name": "vyralc0re", "creator_id": core}).json()["id"]
    sid = c.post("/api/sources", json={"input": "twitch.tv/silky", "platform": "twitch", "creator_ids": [silky]}).json()["id"]
    assert c.post("/api/funnel/routes", json={"source_id": sid, "destination_id": page, "allow_cross_creator": True}).status_code in (200, 201)
    fake.posts = [RemotePost("S1", "https://www.twitch.tv/silky/clip/S1", "silky moment", posted_at=datetime.now(timezone.utc) + timedelta(seconds=5), views=500)]
    assert ctx.pipeline.check_source(sid)["new"] == 1
    drain(ctx)
    ref = c.get("/api/references").json()[0]
    assert ref["status"] == "ready", ref["status_detail"]
    assert [o["destination"]["display_name"] for o in c.get("/api/clips").json()[0]["outputs"]] == ["vyralc0re"]


def test_a_stream_still_live_is_skipped_not_downloaded_forever(env):
    """The moment is in a stream that's still going: its audio isn't downloaded (that would never finish).
    Vyral waits and looks again, and makes the clip once the stream has ended."""
    ctx, c, fake = env
    _, sid, *_ = setup_accounts(c)
    fake.posts = []
    ctx.pipeline.check_source(sid)
    fake.live = {"https://www.twitch.tv/videos/2"}
    fake.posts = [RemotePost("lv1", "https://www.tiktok.com/@a.clips/video/lv1", "live moment")]
    ctx.pipeline.check_source(sid)
    drain(ctx)  # runs the first attempt; the retry is scheduled 30 minutes out
    ref = c.get("/api/references").json()[0]
    assert ref["status"] == "new" and "still live" in ref["status_detail"], ref["status_detail"]
    assert ("audio", "https://www.twitch.tv/videos/2") not in fake.calls
    # The stream ends; the scheduled retry finds the moment.
    fake.live = set()
    assert ctx.pipeline.build_clip(ref["id"], None, 1)["status"] == "ready"


def test_stop_ends_a_long_search(env):
    """Stop works while Vyral is searching streams, not just before it starts."""
    ctx, c, fake = env
    _, sid, *_ = setup_accounts(c)
    fake.posts = []
    ctx.pipeline.check_source(sid)
    fake.posts = [RemotePost("st1", "https://www.tiktok.com/@a.clips/video/st1", "stop me")]
    ctx.pipeline.check_source(sid)
    rid = c.get("/api/references").json()[0]["id"]
    assert ctx.pipeline.build_clip(rid, stop_requested=lambda: True) == {"status": "stopped"}
    assert not any(call[0] == "audio" and "twitch" in call[1] for call in fake.calls)  # no stream was downloaded
    r = c.post(f"/api/references/{rid}/stop").json()
    assert r["status"] == "failed" and "Stopped" in r["status_detail"]
    jobs = c.get("/api/jobs").json()
    assert all(j["status"] != "queued" for j in jobs if j["kind"] == "clip.build")


def test_streamer_names_are_given_to_the_speech_model(env):
    ctx, c, fake = env
    _, sid, *_ = setup_accounts(c)
    fake.posts = []
    ctx.pipeline.check_source(sid)
    fake.posts = [RemotePost("hn1", "https://www.tiktok.com/@a.clips/video/hn1", "names")]
    ctx.pipeline.check_source(sid)
    drain(ctx)
    assert ctx.transcriber.hints == ["Streamer A", "streamera"]

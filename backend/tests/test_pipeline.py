"""The automatic loop end to end: real audio matching, real FFmpeg renders, simulated internet."""
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import pytest
import respx
from fastapi.testclient import TestClient

from clippr.app import build_context, create_app
from clippr.config import Config
from clippr.fetch import FetchError, RemotePost, RemoteVod
from clippr.media.ffmpeg import probe, run
from clippr.models import Clip, ClipOutput, ReferenceVideo
from clippr.secrets_store import MemoryStore
from media_fixtures import make_stream_and_clip, speechlike, write_wav

HOOK = "https://discord.com/api/webhooks/123456789/abcdefghijklmnopqrstuvwxyz_123"
TOKEN = "test-token"


@pytest.fixture(scope="session")
def media(tmp_path_factory):
    d = tmp_path_factory.mktemp("media")
    stream, clip = make_stream_and_clip(d, stream_s=240, at=131.0, clip_s=20, video=True)
    write_wav(d / "other.wav", speechlike(240, 42))
    other = d / "other.mp4"
    run(["-f", "lavfi", "-i", "color=c=gray:size=640x360:rate=30:duration=240", "-i", str(d / "other.wav"), "-shortest",
         "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", str(other)])
    return {"stream": stream, "clip": clip, "other": other}


class FakeFetcher:
    """Plays the part of TikTok + Twitch using local files."""

    def __init__(self, media):
        self.m = media
        self.posts: list[RemotePost] = []
        self.calls: list[tuple] = []
        self.fail_listing = False

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
        src = self.m["stream"] if url.endswith("/videos/2") else self.m["other"] if url.endswith("/videos/1") else self.m["clip"]
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


@pytest.fixture
def env(tmp_path, media, monkeypatch):
    monkeypatch.setenv("CLIPPR_RENDER_PRESET", "ultrafast")
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path / "home"))
    fake = FakeFetcher(media)
    cfg = Config(data_dir=tmp_path / "data", port=8765, api_token=TOKEN, run_worker=False, secret_backend="memory")
    ctx = build_context(cfg, secrets=MemoryStore(), fetcher=fake)
    with TestClient(create_app(ctx=ctx), base_url="http://127.0.0.1:8765", headers={"X-Clippr-Token": TOKEN}) as c:
        yield ctx, c, fake


def drain(ctx):
    n = 0
    while ctx.jobs.run_one():
        n += 1
    return n


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
    cid, sid, tt, yt = setup_accounts(c)

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
    assert tdesc.startswith("He actually did it 😭") and "#fyp" not in tdesc and "@someone" not in tdesc
    assert "Follow for more" in tdesc and "#gaming #clips #StreamerA" in tdesc
    assert outs["youtube"]["title"] == "He actually did it 😭" and "#shorts" in outs["youtube"]["description"]
    assert outs["tiktok"]["destination"]["handle"] == "@streamera.tt"

    # Rendered from the original stream, cut to the moment (20 s clip + 3 s jump cut + padding).
    with ctx.db.session() as s:
        path = Path(s.get(ClipOutput, outs["tiktok"]["id"]).file_path)
    info = probe(path)
    assert 22.5 < info.duration < 25.5 and info.has_audio

    # Discord got "new post" then "ready" with both platforms.
    msgs = [httpx.Request("POST", HOOK, content=call.request.content) for call in discord.calls]
    bodies = [call.request.content.decode() for call in discord.calls]
    assert len(msgs) == 2 and "a.clips" in bodies[0] and "just posted" in bodies[0]
    assert "Clip ready for upload" in bodies[1] and "TikTok" in bodies[1] and "YouTube" in bodies[1] and "@streamera.tt" in bodies[1]

    # Preview stream works with the token in the query (for <video src>), not without.
    oid = outs["tiktok"]["id"]
    assert c.get(f"/api/media/outputs/{oid}", headers={"X-Clippr-Token": ""}, params={"t": TOKEN}).status_code == 200
    assert c.get(f"/api/media/outputs/{oid}", headers={"X-Clippr-Token": ""}).status_code == 401

    # Save to Downloads, edit caption, mark uploaded.
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
    cid, sid, *_ = setup_accounts(c)
    c.post("/api/sources", json={"input": "https://www.twitch.tv/somestreamer"})  # not watchable, must be skipped
    assert ctx.pipeline.tick()["queued"] == 1
    assert ctx.pipeline.tick()["queued"] == 0  # not due again yet
    fake.fail_listing = True
    drain(ctx)
    src = next(x for x in c.get("/api/sources").json() if x["id"] == sid)
    assert "Couldn't check" in src["last_error"]
    assert datetime.fromisoformat(src["next_check_at"]) > datetime.now(timezone.utc) + timedelta(minutes=15)
    assert c.post(f"/api/sources/{sid}/check").status_code == 200
    twitch = next(x for x in c.get("/api/sources").json() if x["platform"] == "twitch")
    assert c.post(f"/api/sources/{twitch['id']}/check").status_code == 422
    c.put("/api/settings", json={"monitoring": {"enabled": False}})
    assert ctx.pipeline.tick() == {"monitoring": "off"}


def test_creator_links_and_webhook_validation(env):
    ctx, c, _ = env
    r = c.post("/api/creators", json={"name": "X", "vod_channels": ["twitch.tv/xqc", "https://www.youtube.com/@Someone/videos", "https://evil.com/a"]})
    assert r.status_code == 422 and "evil.com" in r.json()["error"]["message"]
    r = c.post("/api/creators", json={"name": "X", "vod_channels": ["twitch.tv/xqc", "https://www.youtube.com/@Someone/videos"]})
    assert r.json()["vod_channels"] == ["https://twitch.tv/xqc", "https://www.youtube.com/@Someone/videos"]
    for bad in ["https://example.com/api/webhooks/1/x", "http://discord.com/api/webhooks/123456/abcdefghijklmnopqrstuvwxyz", "not a url"]:
        assert c.put("/api/notifications", json={"webhook_url": bad}).status_code == 422
    assert c.post("/api/notifications/test").status_code == 409
    assert c.get("/api/notifications").json()["configured"] is False

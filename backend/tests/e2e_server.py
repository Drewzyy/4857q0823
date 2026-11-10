"""Starts Vyral for the browser tests with one real clip already made through the real pipeline
(stream matching + FFmpeg render), using local files instead of TikTok/Twitch."""
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import os

os.environ.setdefault("CLIPPR_RENDER_PRESET", "ultrafast")
import uvicorn
from fastapi.testclient import TestClient

from clippr.app import build_context, create_app
from clippr.config import Config
from clippr.fetch import RemotePost
from clippr.media.ffmpeg import run
from fakes import FakeFetcher, FakeTranscriber
from media_fixtures import make_stream_and_clip, speechlike, write_wav

port, data_dir, dist = int(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3]).resolve()
media_dir = Path(tempfile.mkdtemp(prefix="vyral-e2e-media-"))
stream, clip = make_stream_and_clip(media_dir, stream_s=120, at=61.0, clip_s=12, video=True)
write_wav(media_dir / "other.wav", speechlike(120, 42))
run(["-f", "lavfi", "-i", "color=c=gray:size=640x360:rate=30:duration=120", "-i", str(media_dir / "other.wav"), "-shortest",
     "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", str(media_dir / "other.mp4")])
fake = FakeFetcher({"stream": stream, "clip": clip, "other": media_dir / "other.mp4"})

cfg = Config(data_dir=data_dir, port=port, api_token="e2e-token", run_worker=False, secret_backend="file")
cfg.frontend_dist = dist
ctx = build_context(cfg, fetcher=fake, transcriber=FakeTranscriber())
app = create_app(ctx=ctx)
h = {"X-Clippr-Token": "e2e-token"}
with TestClient(app, base_url=f"http://127.0.0.1:{port}", headers=h) as c:
    cr = c.post("/api/creators", json={"name": "Streamer A", "clip_permission": True, "vod_channels": ["https://www.twitch.tv/streamera"]}).json()
    sid = c.post("/api/sources", json={"input": "@streamera.clips", "creator_id": cr["id"]}).json()["id"]
    tt = c.post("/api/destinations", json={"platform": "tiktok", "display_name": "Streamer A TikTok", "handle": "@streamera.tt", "creator_id": cr["id"]}).json()
    c.patch(f"/api/destinations/{tt['id']}", json={"settings": {"hashtags": ["#gaming"]}})
    c.post("/api/destinations", json={"platform": "youtube", "display_name": "Streamer A YouTube", "handle": "@streameraYT", "creator_id": cr["id"]})
    fake.posts = []
    ctx.pipeline.check_source(sid)
    fake.posts = [RemotePost("v1", "https://www.tiktok.com/@streamera.clips/video/v1", "He did NOT just say that #fyp")]
    ctx.pipeline.check_source(sid)
    while ctx.jobs.run_one():
        pass
    assert c.get("/api/clips").json(), "seed clip was not created"
ctx.config.run_worker = True  # re-renders run in the background like the real app
print("E2E server ready", flush=True)
uvicorn.run(app, host="127.0.0.1", port=port, log_level="warning")

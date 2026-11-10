from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from clippr.app import build_context, create_app
from clippr.config import Config
from clippr.media.ffmpeg import run
from clippr.secrets_store import MemoryStore
from fakes import FakeFetcher, FakeTranscriber
from media_fixtures import make_stream_and_clip, speechlike, write_wav

TOKEN = "test-token"


@pytest.fixture(autouse=True)
def _offline_emoji(monkeypatch):
    """Tests never download emoji pictures; emoji tests put the pictures in place themselves."""
    monkeypatch.setenv("CLIPPR_OFFLINE_EMOJI", "1")


@pytest.fixture
def ctx(tmp_path):
    cfg = Config(data_dir=tmp_path / "data", port=8765, api_token=TOKEN, run_worker=False, secret_backend="memory")
    return build_context(cfg, secrets=MemoryStore())


@pytest.fixture
def client(ctx):
    app = create_app(ctx=ctx)
    with TestClient(app, base_url="http://127.0.0.1:8765", headers={"X-Clippr-Token": TOKEN}) as c:
        yield c


@pytest.fixture(scope="session")
def media(tmp_path_factory):
    d = tmp_path_factory.mktemp("media")
    stream, clip = make_stream_and_clip(d, stream_s=240, at=131.0, clip_s=20, video=True)
    write_wav(d / "other.wav", speechlike(240, 42))
    other = d / "other.mp4"
    run(["-f", "lavfi", "-i", "color=c=gray:size=640x360:rate=30:duration=240", "-i", str(d / "other.wav"), "-shortest",
         "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", str(other)])
    return {"stream": stream, "clip": clip, "other": other}


@pytest.fixture
def env(tmp_path, media, monkeypatch):
    monkeypatch.setenv("CLIPPR_RENDER_PRESET", "ultrafast")
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path / "home"))
    fake = FakeFetcher(media)
    cfg = Config(data_dir=tmp_path / "data", port=8765, api_token=TOKEN, run_worker=False, secret_backend="memory")
    ctx = build_context(cfg, secrets=MemoryStore(), fetcher=fake, transcriber=FakeTranscriber())
    with TestClient(create_app(ctx=ctx), base_url="http://127.0.0.1:8765", headers={"X-Clippr-Token": TOKEN}) as c:
        yield ctx, c, fake

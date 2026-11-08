import pytest
from fastapi.testclient import TestClient

from clippr.app import build_context, create_app
from clippr.config import Config
from clippr.secrets_store import MemoryStore

TOKEN = "test-token"


@pytest.fixture
def ctx(tmp_path):
    cfg = Config(data_dir=tmp_path / "data", port=8765, api_token=TOKEN, run_worker=False, secret_backend="memory")
    return build_context(cfg, secrets=MemoryStore())


@pytest.fixture
def client(ctx):
    app = create_app(ctx=ctx)
    with TestClient(app, base_url="http://127.0.0.1:8765", headers={"X-Clippr-Token": TOKEN}) as c:
        yield c

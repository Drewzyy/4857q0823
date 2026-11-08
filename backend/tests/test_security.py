from fastapi.testclient import TestClient

from clippr.app import create_app
from clippr.logging_setup import redact


def test_api_requires_token(ctx):
    with TestClient(create_app(ctx=ctx), base_url="http://127.0.0.1:8765") as c:
        assert c.get("/api/health").status_code == 200  # health is public
        r = c.get("/api/sources")
        assert r.status_code == 401
        assert c.get("/api/sources", headers={"X-Clippr-Token": "wrong"}).status_code == 401


def test_dns_rebinding_host_rejected(ctx):
    with TestClient(create_app(ctx=ctx), base_url="http://evil.example:8765", headers={"X-Clippr-Token": "test-token"}) as c:
        assert c.get("/api/sources").status_code == 421


def test_cross_origin_write_blocked(client):
    r = client.post("/api/creators", json={"name": "X"}, headers={"Origin": "https://evil.example"})
    assert r.status_code == 403


def test_security_headers(client):
    r = client.get("/api/sources")
    assert r.headers["x-content-type-options"] == "nosniff"
    assert r.headers["cache-control"] == "no-store"


def test_redaction():
    s = redact('token refresh_token="abc123" client_secret=shh Bearer eyJhbGci.x.y https://x?code=SECRET&state=1')
    assert "abc123" not in s and "shh" not in s and "eyJhbGci" not in s and "SECRET" not in s


def test_errors_do_not_leak_internals(client):
    r = client.get("/api/sources/999999")  # method not allowed / not found shape
    assert "Traceback" not in r.text

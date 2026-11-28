"""The Chrome extension's heartbeat, the per-page lights, the connected timeout, and the extension folder it loads from."""
import json
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from clippr import companion, mcp
from clippr.models import DestinationAccount


def _bridge(ctx):
    return TestClient(mcp.create_app(ctx), base_url="http://127.0.0.1:47821"), {"Authorization": f"Bearer {mcp.token(ctx)}"}


def test_light_rules_match_the_extension():
    acc = {"handle": "@mypage", "display_name": "My page"}
    assert companion.light(acc, None)[0] == "amber"
    assert companion.light(acc, {"signedIn": None})[0] == "amber"
    assert companion.light(acc, {"signedIn": False}) == ("grey", "Not signed in")
    assert companion.light(acc, {"signedIn": True})[0] == "amber"
    assert companion.light(acc, {"signedIn": True, "handle": "@MyPage"})[0] == "green"
    assert companion.light(acc, {"signedIn": True, "name": "my page"})[0] == "green"
    assert companion.light(acc, {"signedIn": True, "handle": "@other"}) == ("amber", "Signed in as @other: switch account")


def test_heartbeat_needs_the_token_and_shows_in_the_app(client, ctx, monkeypatch):
    companion._beat.clear()
    with ctx.db.session() as s:
        s.add(DestinationAccount(platform="tiktok", external_id="a", handle="@mypage", display_name="My page", settings={}))
        s.add(DestinationAccount(platform="youtube", external_id="b", handle="", display_name="Kai Clips", settings={}))
    assert not client.get("/api/companion").json()["connected"]
    mc, auth = _bridge(ctx)
    body = {"version": "1.2.0", "enabled": True, "every": 5, "seen": {
        "tiktok": {"signedIn": True, "handle": "@mypage", "at": "x"}, "youtube": {"signedIn": False}, "evil": {"signedIn": True}}}
    assert mc.post("/companion/status", json=body).status_code == 401
    assert mc.post("/companion/status", json=[1], headers=auth).status_code == 422
    r = mc.post("/companion/status", json=body, headers=auth).json()
    assert r["bundled_version"] == json.loads((companion.extension_dir() / "manifest.json").read_text())["version"]
    st = client.get("/api/companion").json()
    assert st["connected"] and st["version"] == "1.2.0" and st["enabled"] and st["folder"].endswith("chrome-extension")
    lights = {a["platform"]: a["light"] for a in st["accounts"]}
    assert lights == {"tiktok": "green", "youtube": "grey"}
    companion._beat["at"] = datetime.now(timezone.utc) - timedelta(minutes=11)  # more than twice its 5 minute tick
    st = client.get("/api/companion").json()
    assert not st["connected"] and st["last_seen"] and {a["light"] for a in st["accounts"]} == {"amber"}


def test_extension_folder_copied_only_when_the_version_changes(tmp_path, monkeypatch):
    src = tmp_path / "bundled"
    src.mkdir()
    (src / "manifest.json").write_text(json.dumps({"version": "1.0.0"}))
    (src / "background.js").write_text("// one")
    monkeypatch.setattr(companion, "extension_dir", lambda: src)
    data = tmp_path / "data"
    assert companion.install(data)["copied"]
    dest = data / "chrome-extension"
    assert (dest / "background.js").read_text() == "// one"
    (dest / "mine.txt").write_text("left alone")
    assert not companion.install(data)["copied"] and (dest / "mine.txt").exists()  # same version: untouched
    (src / "manifest.json").write_text(json.dumps({"version": "1.1.0"}))
    (src / "background.js").write_text("// two")
    assert companion.install(data)["copied"]
    assert (dest / "background.js").read_text() == "// two" and not (dest / "mine.txt").exists()
    assert sorted(p.name for p in data.iterdir()) == ["chrome-extension"]  # no temp or old copies left behind
    monkeypatch.setattr(companion, "extension_dir", lambda: None)
    assert not companion.install(data)["copied"] and companion.bundled_version() is None


def test_ping_needs_no_token_but_everything_else_still_does(ctx):
    from fastapi.testclient import TestClient
    mc = TestClient(mcp.create_app(ctx), base_url="http://127.0.0.1:47821")
    assert mc.get("/companion/ping").json() == {"ok": True, "app": "vyral"}
    assert mc.get("/companion/ping", headers={"Host": "evil.com"}).status_code == 421
    for method, path in (("get", "/companion/next"), ("get", "/companion/accounts"), ("post", "/companion/status"),
                         ("get", "/companion/video/1"), ("post", "/companion/result")):
        assert getattr(mc, method)(path, headers={"Authorization": "Bearer wrong"}).status_code == 401, path
    assert mc.get("/companion/accounts", headers={"Authorization": f"Bearer {mcp.token(ctx)}"}).status_code == 200

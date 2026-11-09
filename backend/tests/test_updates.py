from fastapi.testclient import TestClient

from clippr.app import create_app

H = {"X-Clippr-Token": "test-token"}


def test_update_handshake_between_ui_and_desktop_shell(ctx):
    ctx.config.desktop_mode = True
    with TestClient(create_app(ctx=ctx), base_url="http://127.0.0.1:8765", headers=H) as c:
        s = c.get("/api/app-update").json()
        assert s["busy"] is False
        assert s["available"] and s["state"] == "idle" and s["current"]
        assert c.post("/api/app-update/install").status_code == 409  # nothing downloaded yet
        assert c.post("/api/app-update/check").json()["check_requested"] is True  # UI asks
        assert c.post("/api/app-update/report", json={"state": "checking"}).json()["check_requested"] is False  # shell picks it up
        c.post("/api/app-update/report", json={"state": "downloading", "version": "0.4.9", "progress": 0.5})
        r = c.post("/api/app-update/report", json={"state": "ready", "version": "0.4.9", "notes": "Fixes"}).json()
        assert r["state"] == "ready" and r["version"] == "0.4.9" and r["checked_at"]
        assert c.post("/api/app-update/install").json()["install_requested"] is True  # UI clicks Restart
        assert c.post("/api/app-update/report", json={"state": "bogus"}).status_code == 422
    # The update endpoints need the window token like every other API call.
    with TestClient(create_app(ctx=ctx), base_url="http://127.0.0.1:8765") as c:
        assert c.post("/api/app-update/report", json={"state": "ready"}).status_code == 401


def test_browser_mode_has_no_updater(client):
    assert client.get("/api/app-update").json()["available"] is False
    assert client.post("/api/app-update/check").status_code == 409

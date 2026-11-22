"""Dropbox auto-upload against a fake Dropbox: sign-in with PKCE, names, byte-for-byte verified uploads, resuming
after a dropped connection, deleting and resending a bad upload, waiting for files to finish, Sync all."""
import base64
import hashlib
import json
import os
import time
import urllib.parse
from datetime import datetime, timedelta, timezone

import httpx
import pytest

from clippr import dropbox, mcp
from clippr.models import Clip, ClipOutput, DropboxUpload


class FakeDropbox:
    def __init__(self):
        self.files: dict[str, bytes] = {}
        self.sessions: dict[str, bytearray] = {}
        self.access = "access-1"
        self.refresh_ok = True
        self.drop_after_append = 0  # appends that land but whose reply never arrives
        self.corrupt = 0  # finishes that store damaged bytes
        self.token_forms: list[dict] = []
        self.revoked = False
        self.account_type = "basic"

    @staticmethod
    def _meta(path, data):
        return {".tag": "file", "name": path.rsplit("/", 1)[1], "path_display": path, "size": len(data), "content_hash": dropbox.hash_bytes(data)}

    @staticmethod
    def _err(summary, error=None):
        return httpx.Response(409, json={"error_summary": summary, "error": error or {".tag": summary.split("/")[0]}})

    def __call__(self, req: httpx.Request) -> httpx.Response:
        route = req.url.path
        if route == "/oauth2/token":
            form = {k: v[0] for k, v in urllib.parse.parse_qs(req.content.decode()).items()}
            self.token_forms.append(form)
            if form["grant_type"] == "refresh_token" and not self.refresh_ok:
                return httpx.Response(400, json={"error": "invalid_grant"})
            self.access = f"access-{len(self.token_forms) + 1}"
            return httpx.Response(200, json={"access_token": self.access, "expires_in": 14400, "refresh_token": "refresh-1", "token_type": "bearer"})
        if req.headers.get("authorization") != f"Bearer {self.access}":
            return httpx.Response(401, json={"error_summary": "expired_access_token/"})
        arg = req.headers.get("dropbox-api-arg")
        args = json.loads(arg) if arg else json.loads(req.content or b"null")
        data = req.content if arg else b""
        if route == "/2/users/get_current_account":
            acct = {"account_id": "dbid:1", "name": {"display_name": "Andrew"}, "account_type": {".tag": self.account_type}}
            return httpx.Response(200, json={**acct, "team": {"name": "Acme"}} if self.account_type == "business" else acct)
        if route == "/2/auth/token/revoke":
            self.revoked = True
            return httpx.Response(200, content=b"")
        if route == "/2/files/get_metadata":
            p = args["path"]
            return httpx.Response(200, json=self._meta(p, self.files[p])) if p in self.files else self._err("path/not_found/")
        if route == "/2/files/delete_v2":
            self.files.pop(args["path"])
            return httpx.Response(200, json={"metadata": {}})
        if route.startswith("/2/files/upload_session/") and route != "/2/files/upload_session/finish":
            if args.get("content_hash") != dropbox.hash_bytes(data):
                return httpx.Response(400, text="content_hash mismatch")
        if route == "/2/files/upload_session/start":
            sid = f"s{len(self.sessions) + 1}"
            self.sessions[sid] = bytearray(data)
            return httpx.Response(200, json={"session_id": sid})
        cur = args.get("cursor", {})
        buf = self.sessions.get(cur.get("session_id"))
        if buf is None:
            return self._err("lookup_failed/not_found/", {".tag": "lookup_failed", "lookup_failed": {".tag": "not_found"}})
        if cur["offset"] != len(buf):
            return self._err("incorrect_offset/", {".tag": "incorrect_offset", "correct_offset": len(buf)})
        if route == "/2/files/upload_session/append_v2":
            buf.extend(data)
            if self.drop_after_append:
                self.drop_after_append -= 1
                raise httpx.ConnectError("connection reset")
            return httpx.Response(200, content=b"")
        if route == "/2/files/upload_session/finish":
            path = args["commit"]["path"]
            assert args["commit"]["mode"] == "add" and args["commit"]["autorename"] is False
            if path in self.files:
                return self._err("path/conflict/file/")
            stored = bytes(buf)
            if self.corrupt:
                self.corrupt -= 1
                stored = stored[:-1] + bytes([stored[-1] ^ 0xFF])
            self.files[path] = stored
            return httpx.Response(200, json=self._meta(path, stored))
        return httpx.Response(404)


@pytest.fixture
def box(ctx, tmp_path, monkeypatch):
    monkeypatch.setattr(dropbox, "STABLE_SECONDS", 0)
    monkeypatch.setattr(dropbox, "SCAN_EVERY", 0)
    monkeypatch.setattr(dropbox, "CHUNK", 1 << 20)  # several pieces for a few MB
    monkeypatch.setattr(dropbox.net, "online", lambda: True)
    monkeypatch.setenv("CLIPPR_DOWNLOADS_DIR", str(tmp_path / "downloads"))
    fake = FakeDropbox()
    sync = dropbox.DropboxSync(ctx, http=httpx.Client(transport=httpx.MockTransport(fake)))
    ctx.dropbox = sync
    yield fake, sync
    sync.stop()


def _connect(ctx, sync, fake):
    with ctx.db.session() as s:
        from clippr.api.system import SETTINGS_KEY
        from clippr.models import Setting
        s.merge(Setting(key=SETTINGS_KEY, value={"dropbox": {"app_key": "abc123", "folder": "/Vyral", "auto_upload": True}}))
    url = sync.begin_connect("abc123")
    q = {k: v[0] for k, v in urllib.parse.parse_qs(urllib.parse.urlparse(url).query).items()}
    assert q["scope"] == "files.content.write files.content.read" and "team" not in q["scope"]
    assert q["code_challenge_method"] == "S256" and q["token_access_type"] == "offline" and q["redirect_uri"] == dropbox.REDIRECT_URI
    ok, msg = sync.finish_connect({"code": "the-code", "state": q["state"]})
    assert ok, msg
    form = fake.token_forms[-1]
    challenge = base64.urlsafe_b64encode(hashlib.sha256(form["code_verifier"].encode()).digest()).rstrip(b"=").decode()
    assert challenge == q["code_challenge"] and form["grant_type"] == "authorization_code"
    time.sleep(0.01)


def _render(ctx, tmp_path, folder="ref31-1795094064762", size=3_500_000, seed=1):
    d = tmp_path / "media" / "clips" / folder
    d.mkdir(parents=True, exist_ok=True)
    f = d / "render-0.mp4"
    f.write_bytes(os.urandom(16) + bytes((i * seed) % 251 for i in range(size)))
    with ctx.db.session() as s:
        clip = Clip(expires_at=datetime.now(timezone.utc) + timedelta(days=30), files_dir=str(d))
        s.add(clip)
        s.flush()
        o = ClipOutput(clip_id=clip.id, platform="tiktok", file_path=str(f), render_state="ready")
        s.add(o)
        s.flush()
        return f, o.id


def _run(sync, ticks=8):
    for _ in range(ticks):
        sync.tick()


def _row(ctx, f):
    with ctx.db.session() as s:
        return dropbox.status_for(s, str(f))


def test_content_hash_is_dropboxs_block_hash(tmp_path):
    data = os.urandom(9 * 1024 * 1024 + 5)
    blocks = [data[i:i + dropbox.BLOCK] for i in range(0, len(data), dropbox.BLOCK)]
    want = hashlib.sha256(b"".join(hashlib.sha256(b).digest() for b in blocks)).hexdigest()
    (tmp_path / "f").write_bytes(data)
    assert dropbox.hash_bytes(data) == want == dropbox.content_hash(tmp_path / "f")


def test_connect_keeps_only_the_refresh_token_in_the_credential_store(ctx, box, client):
    fake, sync = box
    _connect(ctx, sync, fake)
    assert ctx.secrets.get(dropbox.SECRET_KEY) == {"refresh_token": "refresh-1", "app_key": "abc123"}
    view = client.get("/api/dropbox").json()
    assert view["connected"] and view["account"] == "Andrew"
    with ctx.db.session() as s:
        from clippr.models import Setting
        assert "refresh" not in json.dumps([r.value for r in s.query(Setting).all()])
    assert sync.finish_connect({"code": "x", "state": "forged"})[0] is False


def test_a_finished_render_goes_up_byte_for_byte_under_its_clip_folder_name(ctx, box, tmp_path, client):
    fake, sync = box
    _connect(ctx, sync, fake)
    f, oid = _render(ctx, tmp_path)
    _run(sync)
    st = _row(ctx, f)
    assert st["status"] == "uploaded" and st["path"] == "/Vyral/ref31-1795094064762.mp4"
    assert fake.files["/Vyral/ref31-1795094064762.mp4"] == f.read_bytes()
    clip_out = [o for c in client.get("/api/clips").json() for o in c["outputs"] if o["id"] == oid][0]
    assert clip_out["dropbox"]["status"] == "uploaded"
    with ctx.db.session() as s:
        assert mcp._out(s.get(ClipOutput, oid))["dropbox_path"] == "/Vyral/ref31-1795094064762.mp4"


def test_names_skip_the_same_file_and_never_overwrite_a_different_one(ctx, box, tmp_path):
    fake, sync = box
    _connect(ctx, sync, fake)
    f, _ = _render(ctx, tmp_path, folder="ref1-1")
    fake.files["/Vyral/ref1-1.mp4"] = b"someone else's file"
    g, _ = _render(ctx, tmp_path, folder="ref2-2", seed=3)
    fake.files["/Vyral/ref2-2.mp4"] = g.read_bytes()
    starts = len(fake.sessions)
    _run(sync)
    assert fake.files["/Vyral/ref1-1.mp4"] == b"someone else's file"
    assert fake.files["/Vyral/ref1-1-2.mp4"] == f.read_bytes() and _row(ctx, f)["path"] == "/Vyral/ref1-1-2.mp4"
    assert _row(ctx, g)["status"] == "uploaded" and _row(ctx, g)["path"] == "/Vyral/ref2-2.mp4"
    assert len(fake.sessions) == starts + 1  # the one already there wasn't sent again


def test_a_dropped_connection_carries_on_and_leaves_nothing_partial(ctx, box, tmp_path):
    fake, sync = box
    _connect(ctx, sync, fake)
    f, _ = _render(ctx, tmp_path)
    fake.drop_after_append = 1
    _run(sync, 3)
    st = _row(ctx, f)
    assert st["status"] == "failed" and "dropped" in st["error"] and not fake.files  # nothing half-sent shows in Dropbox
    with ctx.db.session() as s:
        r = s.query(DropboxUpload).one()
        assert r.session_id and r.session_offset > 0
        r.next_try_at = datetime.now(timezone.utc) - timedelta(seconds=1)
    _run(sync)
    assert _row(ctx, f)["status"] == "uploaded" and fake.files["/Vyral/ref31-1795094064762.mp4"] == f.read_bytes()
    assert len(fake.sessions) == 1  # same session, carried on


def test_a_copy_that_doesnt_match_is_deleted_and_sent_again(ctx, box, tmp_path):
    fake, sync = box
    _connect(ctx, sync, fake)
    f, _ = _render(ctx, tmp_path)
    fake.corrupt = 1
    _run(sync, 3)
    st = _row(ctx, f)
    assert st["status"] == "failed" and "didn't match" in st["error"] and not fake.files
    sync.retry(st["id"])
    _run(sync)
    assert _row(ctx, f)["status"] == "uploaded" and fake.files["/Vyral/ref31-1795094064762.mp4"] == f.read_bytes()


def test_a_file_still_being_written_waits(ctx, box, tmp_path, monkeypatch):
    fake, sync = box
    _connect(ctx, sync, fake)
    monkeypatch.setattr(dropbox, "STABLE_SECONDS", 6)
    f, _ = _render(ctx, tmp_path)
    for i in range(4):
        with open(f, "ab") as h:
            h.write(b"x" * 1000)
        sync.tick()
    assert _row(ctx, f)["status"] == "queued" and not fake.files


def test_waits_while_disconnected_and_sync_all_sends_older_videos(ctx, box, tmp_path, client):
    fake, sync = box
    old, _ = _render(ctx, tmp_path, folder="ref-old")
    os.utime(old, (time.time() - 3600, time.time() - 3600))
    _run(sync)
    assert _row(ctx, old) is None  # not connected: nothing happens
    _connect(ctx, sync, fake)
    _run(sync)
    assert _row(ctx, old) is None  # made before Dropbox was connected: only Sync all sends it
    saved = tmp_path / "downloads" / "Vyral"
    saved.mkdir(parents=True)
    (saved / "Page - Title.mp4").write_bytes(old.read_bytes())  # a saved copy of the same video
    assert client.post("/api/dropbox/sync-all").json()["queued"] == 2
    _run(sync)
    assert _row(ctx, old)["status"] == "uploaded"
    assert _row(ctx, saved / "Page - Title.mp4")["path"] == "/Vyral/ref-old.mp4"  # not sent twice
    assert list(fake.files) == ["/Vyral/ref-old.mp4"]


def test_an_expired_access_token_is_renewed_and_a_revoked_sign_in_asks_to_reconnect(ctx, box, tmp_path, client):
    fake, sync = box
    _connect(ctx, sync, fake)
    fake.access = "rotated-by-dropbox"  # Vyral's access token stops working
    f, _ = _render(ctx, tmp_path, folder="a")
    _run(sync)
    assert _row(ctx, f)["status"] == "uploaded" and fake.token_forms[-1]["grant_type"] == "refresh_token"
    fake.access, fake.refresh_ok = "rotated-again", False
    g, _ = _render(ctx, tmp_path, folder="b", seed=5)
    _run(sync)
    assert _row(ctx, g)["status"] == "queued"
    assert client.get("/api/dropbox").json()["needs_reconnect"] is True
    client.post("/api/dropbox/disconnect")
    assert ctx.secrets.get(dropbox.SECRET_KEY) is None


def test_folder_setting_is_a_dropbox_path(client):
    assert client.put("/api/settings", json={"dropbox": {"folder": "Vyral/clips/"}}).json()["dropbox"]["folder"] == "/Vyral/clips"
    assert client.put("/api/settings", json={"dropbox": {"folder": "/a/../b"}}).status_code == 422


def test_a_business_account_is_turned_away_and_not_kept(ctx, box):
    fake, sync = box
    fake.account_type = "business"
    url = sync.begin_connect("abc123")
    state = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)["state"][0]
    ok, msg = sync.finish_connect({"code": "c", "state": state})
    assert not ok and "personal" in msg and fake.revoked
    assert ctx.secrets.get(dropbox.SECRET_KEY) is None
    with ctx.db.session() as s:
        assert not dropbox.state(s).get("connected")

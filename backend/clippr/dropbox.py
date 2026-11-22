"""Dropbox auto-upload: every finished video lands in your Dropbox exactly as Vyral rendered it, so Muse can take it
from there.

- Connecting: OAuth 2 (authorization code with PKCE) against your own Dropbox app, whose app key goes in Settings.
  PKCE needs no app secret, so none is asked for or kept. Dropbox sends the browser back to a one-off listener on
  127.0.0.1:53682 that stays open for 10 minutes. Only the refresh token is kept, in the OS credential store
  (Windows Credential Manager, the macOS Keychain). The short-lived access token stays in memory and is renewed
  when it runs out. The credential store is only read once Dropbox has been connected.
- What goes up: each page's video once its render is ready, and new .mp4 files in the save folder ("Save to
  computer"). A file goes up only after its size has held still for 6 seconds, so nothing half-written is sent.
  Videos made before Dropbox was connected go up with Sync all.
- File name: the clip's folder, like ref31-1795094064762.mp4. If that name is taken by a file with the same size and
  content, it's skipped. If it's taken by a different file, -2, -3 and so on are added. Nothing in Dropbox is ever
  overwritten. A copy of a video that is already up (the save folder holds copies) isn't sent twice.
- Uploading: the file's bytes as they are. Nothing is re-encoded, resized or re-muxed. They go in 8 MB pieces
  through an upload session, each piece checked by Dropbox against its hash. A dropped connection carries on from
  the last piece Dropbox has, and nothing shows in Dropbox until the last piece is in. The finished file is then
  read back: its size and content hash must match the local file, or that upload is deleted and sent again. Only
  then is the video marked uploaded.
- Failures retry by themselves (30 s, 1 min, 2 min, 4 min and so on, at most an hour apart). While Dropbox is
  disconnected or the internet is down, uploads wait in the queue and go when it's back.
"""
from __future__ import annotations

import base64
import hashlib
import http.server
import json
import logging
import re
import secrets as pysecrets
import threading
import time
import urllib.parse
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import net
from .api.system import load_settings, save_folder
from .audit import audit
from .models import ClipOutput, DropboxUpload, Setting

log = logging.getLogger("clippr.dropbox")

SECRET_KEY = "dropbox"  # in the credential store: {"refresh_token", "app_key"}
STATE_KEY = "dropbox"  # in the settings table: connected, account name, since when (nothing secret)
REDIRECT_PORT = 53682
REDIRECT_URI = f"http://127.0.0.1:{REDIRECT_PORT}/"
AUTH_URL = "https://www.dropbox.com/oauth2/authorize"
TOKEN_URL = "https://api.dropboxapi.com/oauth2/token"
API = "https://api.dropboxapi.com/2"
CONTENT = "https://content.dropboxapi.com/2"
# The only permissions asked for. No team scopes: Vyral works with a personal (Basic, Plus, Essentials) account only.
SCOPES = "files.content.write files.content.read"
CHUNK = 8 * 1024 * 1024  # each upload piece; a multiple of Dropbox's 4 MB hash block
BLOCK = 4 * 1024 * 1024
STABLE_SECONDS = 6  # a file's size must hold still this long before it's sent
SCAN_EVERY = 5  # seconds between looks for new videos
LOGIN_SECONDS = 600


class DropboxError(Exception):
    pass


class AuthError(DropboxError):
    """Dropbox no longer accepts the sign-in: it has to be connected again."""


class ApiError(DropboxError):
    def __init__(self, summary: str, error: dict | None) -> None:
        super().__init__(summary)
        self.summary, self.error = summary, error or {}


def _hash_blocks(blocks) -> str:
    whole = hashlib.sha256()
    for b in blocks:
        whole.update(hashlib.sha256(b).digest())
    return whole.hexdigest()


def hash_bytes(data: bytes) -> str:
    """Dropbox's content hash: SHA-256 of the SHA-256 of each 4 MB block."""
    return _hash_blocks(data[i:i + BLOCK] for i in range(0, len(data), BLOCK))


def content_hash(path: Path) -> str:
    def blocks():
        with open(path, "rb") as f:
            while b := f.read(BLOCK):
                yield b
    return _hash_blocks(blocks())


def _correct_offset(err) -> int | None:
    if isinstance(err, dict):
        if isinstance(err.get("correct_offset"), int):
            return err["correct_offset"]
        for v in err.values():
            found = _correct_offset(v)
            if found is not None:
                return found
    return None


def safe_name(name: str) -> str:
    name = re.sub(r'[\\/:*?"<>|\x00-\x1f]', "-", name).strip().rstrip(".")
    return name[:180] or "clip"


def state(s: Session) -> dict:
    row = s.get(Setting, STATE_KEY)
    return dict(row.value) if row else {}


def _save_state(s: Session, **kw) -> dict:
    row = s.get(Setting, STATE_KEY)
    value = {**(row.value if row else {}), **kw}
    if row:
        row.value = value
    else:
        s.add(Setting(key=STATE_KEY, value=value))
    return value


def status_for(s: Session, file_path: str | None) -> dict | None:
    """The Dropbox copy of this video file, for the app and Muse: None if it isn't queued at all."""
    r = s.scalar(select(DropboxUpload).where(DropboxUpload.local_path == file_path)) if file_path else None
    if not r:
        return None
    progress = round(r.session_offset / r.size_bytes * 100) if r.status == "uploading" and r.size_bytes else None
    return {"id": r.id, "status": r.status, "path": r.dropbox_path, "error": r.error, "progress": progress,
            "next_try_at": r.next_try_at.isoformat() if r.next_try_at and r.status == "failed" else None,
            "uploaded_at": r.uploaded_at.isoformat() if r.uploaded_at else None}


class Client:
    """The few Dropbox API calls Vyral needs, signed in with the refresh token."""

    def __init__(self, app_key: str, refresh_token: str, http: httpx.Client | None = None) -> None:
        self.app_key, self.refresh_token = app_key, refresh_token
        self._http = http or httpx.Client(timeout=httpx.Timeout(120, connect=20))
        self._token: str | None = None
        self._expires = 0.0

    def _access(self, renew: bool = False) -> str:
        if renew or not self._token or time.monotonic() > self._expires - 60:
            r = self._http.post(TOKEN_URL, data={"grant_type": "refresh_token", "refresh_token": self.refresh_token, "client_id": self.app_key})
            if r.status_code in (400, 401):
                raise AuthError("Dropbox no longer accepts Vyral's sign-in. Connect Dropbox again in Settings.")
            if r.status_code != 200:
                raise DropboxError(f"Dropbox sign-in renewal failed ({r.status_code})")
            j = r.json()
            self._token, self._expires = j["access_token"], time.monotonic() + float(j.get("expires_in", 14400))
        return self._token

    def call(self, host: str, route: str, args: dict | None = None, data: bytes | None = None) -> dict:
        for renew in (False, True):
            headers = {"Authorization": f"Bearer {self._access(renew)}"}
            if host == CONTENT:
                headers["Dropbox-API-Arg"] = json.dumps(args or {}, ensure_ascii=True)  # the header must be plain ASCII
                headers["Content-Type"] = "application/octet-stream"
                r = self._http.post(f"{host}/{route}", headers=headers, content=data or b"")
            elif args is None:
                r = self._http.post(f"{host}/{route}", headers=headers)
            else:
                r = self._http.post(f"{host}/{route}", headers=headers, json=args)
            if r.status_code == 401 and not renew:
                continue  # the access token ran out early: renew it once
            if r.status_code == 401:
                raise AuthError("Dropbox no longer accepts Vyral's sign-in. Connect Dropbox again in Settings.")
            if r.status_code == 409:
                j = r.json()
                raise ApiError(j.get("error_summary", "conflict"), j.get("error"))
            if r.status_code == 429 or r.status_code >= 500:
                raise DropboxError(f"Dropbox is busy ({r.status_code}); trying again shortly")
            if r.status_code != 200:
                raise DropboxError(f"Dropbox refused the request ({r.status_code}): {r.text[:200]}")
            return r.json() if r.content else {}
        raise AuthError("Dropbox sign-in failed")

    def account(self) -> dict:
        return self.call(API, "users/get_current_account")

    def metadata(self, path: str) -> dict | None:
        try:
            return self.call(API, "files/get_metadata", {"path": path})
        except ApiError as e:
            if "not_found" in e.summary:
                return None
            raise

    def delete(self, path: str) -> None:
        self.call(API, "files/delete_v2", {"path": path})

    def revoke(self) -> None:
        self.call(API, "auth/token/revoke")

    def start(self, data: bytes) -> str:
        return self.call(CONTENT, "files/upload_session/start", {"close": False, "content_hash": hash_bytes(data)}, data)["session_id"]

    def append(self, session_id: str, offset: int, data: bytes) -> None:
        self.call(CONTENT, "files/upload_session/append_v2",
                  {"cursor": {"session_id": session_id, "offset": offset}, "close": False, "content_hash": hash_bytes(data)}, data)

    def finish(self, session_id: str, offset: int, path: str) -> dict:
        return self.call(CONTENT, "files/upload_session/finish",
                         {"cursor": {"session_id": session_id, "offset": offset},
                          "commit": {"path": path, "mode": "add", "autorename": False, "mute": True, "strict_conflict": True}})


class DropboxSync:
    """Signs in, finds finished videos and uploads them one at a time on its own thread."""

    def __init__(self, ctx, http: httpx.Client | None = None) -> None:
        self.ctx = ctx
        self._http = http
        self._client: Client | None = None
        self._stop = threading.Event()
        self._wake = threading.Event()
        self._thread: threading.Thread | None = None
        self._seen: dict[str, tuple[int, float, float]] = {}  # path -> (size, mtime, first seen with them)
        self._scanned = 0.0
        self._login: dict | None = None
        self._server: http.server.HTTPServer | None = None
        self._lock = threading.Lock()

    # ---------- lifecycle ----------
    def start(self) -> None:
        with self.ctx.db.session() as s:  # an upload cut off by quitting carries on from its last piece
            for r in s.scalars(select(DropboxUpload).where(DropboxUpload.status == "uploading")):
                r.status = "queued"
        self._stop.clear()
        self._thread = threading.Thread(target=self._run, name="dropbox", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()
        self._close_listener()

    def wake(self) -> None:
        self._wake.set()

    def _run(self) -> None:
        while not self._stop.is_set():
            busy = False
            try:
                busy = self.tick()
            except Exception:
                log.exception("Dropbox sync step failed")
            if not busy and self._wake.wait(2.0):
                self._wake.clear()

    # ---------- signing in ----------
    def connecting(self) -> bool:
        return bool(self._login and time.monotonic() < self._login["until"])

    def begin_connect(self, app_key: str) -> str:
        verifier = pysecrets.token_urlsafe(64)
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
        login = {"verifier": verifier, "state": pysecrets.token_urlsafe(24), "app_key": app_key, "until": time.monotonic() + LOGIN_SECONDS}
        with self._lock:
            if not self._server:
                error: OSError | None = None
                for wait in (0.1, 0.3, 0.6, 1.0, 0):  # the last sign-in's listener may still be closing
                    try:
                        self._server = http.server.HTTPServer(("127.0.0.1", REDIRECT_PORT), self._handler())
                        break
                    except OSError as e:
                        error = e
                        time.sleep(wait)
                if not self._server:
                    raise DropboxError(f"Vyral couldn't listen on 127.0.0.1:{REDIRECT_PORT} for Dropbox's reply "
                                       f"({getattr(error, 'strerror', None) or error}). Close whatever is using that port and try again.")
                threading.Thread(target=self._server.serve_forever, name="dropbox-login", daemon=True).start()
                timer = threading.Timer(LOGIN_SECONDS, self._close_listener, (self._server,))
                timer.daemon = True
                timer.start()
            self._login = login
        return AUTH_URL + "?" + urllib.parse.urlencode({
            "client_id": app_key, "response_type": "code", "code_challenge": challenge, "code_challenge_method": "S256",
            "token_access_type": "offline", "scope": SCOPES, "redirect_uri": REDIRECT_URI, "state": login["state"]})

    def _close_listener(self, only=None) -> None:
        with self._lock:
            if only is not None and self._server is not only:
                return  # an older sign-in's timer: the listener now open belongs to a newer one
            server, self._server = self._server, None
        if server:
            threading.Thread(target=lambda: (server.shutdown(), server.server_close()), daemon=True).start()

    def _handler(self):
        sync = self

        class Handler(http.server.BaseHTTPRequestHandler):
            def log_message(self, *a) -> None:  # the query holds the sign-in code: never logged
                pass

            def do_GET(self) -> None:  # noqa: N802
                url = urllib.parse.urlparse(self.path)
                if url.path != "/":
                    self.send_error(404)
                    return
                q = {k: v[0] for k, v in urllib.parse.parse_qs(url.query).items()}
                ok, message = sync.finish_connect(q)
                body = (f"<!doctype html><meta charset=utf-8><title>Vyral</title><body style='font-family:system-ui;padding:40px'>"
                        f"<h2>{'Dropbox is connected' if ok else 'Dropbox was not connected'}</h2><p>{message}</p>"
                        "<p>You can close this tab and go back to Vyral.</p>").encode()
                self.send_response(200 if ok else 400)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.end_headers()
                self.wfile.write(body)

        return Handler

    def finish_connect(self, q: dict) -> tuple[bool, str]:
        """Dropbox's reply to the browser: check it's the sign-in Vyral started, then trade the code for tokens."""
        login = self._login
        if not login or time.monotonic() > login["until"] or not pysecrets.compare_digest(q.get("state", ""), login["state"]):
            return False, "This sign-in link is old or wasn't started by Vyral. Press Connect in Vyral's Settings again."
        self._login = None
        self._close_listener()
        if q.get("error"):
            return False, "Dropbox access wasn't allowed."
        try:
            r = (self._http or httpx).post(TOKEN_URL, data={"code": q.get("code", ""), "grant_type": "authorization_code", "client_id": login["app_key"],
                                                            "code_verifier": login["verifier"], "redirect_uri": REDIRECT_URI}, timeout=30)
            if r.status_code != 200:
                return False, f"Dropbox didn't accept the sign-in ({r.json().get('error_description', r.status_code) if r.content else r.status_code})."
            j = r.json()
            client = Client(login["app_key"], j["refresh_token"], self._http)
            client._token, client._expires = j["access_token"], time.monotonic() + float(j.get("expires_in", 14400))
            account = client.account()
            business = account.get("team") or (account.get("account_type") or {}).get(".tag") == "business" \
                or any(x.startswith("team") for x in str(j.get("scope", "")).split())
            if business:  # not kept: Vyral only works with a personal Dropbox
                client.revoke()
        except (httpx.HTTPError, DropboxError, KeyError, ValueError) as e:
            log.warning("Dropbox sign-in failed: %s", type(e).__name__)
            return False, "Vyral couldn't reach Dropbox to finish signing in. Check the internet connection and try again."
        if business:
            return False, "That's a Dropbox Business (team) account. Vyral only connects to a personal Dropbox: sign in with your personal account."
        self.ctx.secrets.set(SECRET_KEY, {"refresh_token": j["refresh_token"], "app_key": login["app_key"]})
        name = (account.get("name") or {}).get("display_name") or account.get("email") or "your Dropbox"
        with self.ctx.db.session() as s:
            st = state(s)
            _save_state(s, connected=True, needs_reconnect=False, account=name, account_id=account.get("account_id"), error=None,
                        since=st.get("since") or datetime.now(timezone.utc).isoformat())
            audit(s, "dropbox.connected", "dropbox", "", {})
        self._client = client
        self.wake()
        return True, f"Vyral will upload finished videos to {name}'s Dropbox."

    def disconnect(self) -> None:
        client = self._get_client()
        if client:
            try:
                client.revoke()
            except (httpx.HTTPError, DropboxError):
                pass  # forgetting the sign-in here is what matters
        self._client = None
        self.ctx.secrets.delete(SECRET_KEY)
        with self.ctx.db.session() as s:
            _save_state(s, connected=False, needs_reconnect=False, account=None, account_id=None, error=None)
            audit(s, "dropbox.disconnected", "dropbox", "", {})

    def _get_client(self) -> Client | None:
        if self._client:
            return self._client
        with self.ctx.db.session() as s:
            st = state(s)
        if not st.get("connected") or st.get("needs_reconnect"):
            return None  # the credential store isn't touched until Dropbox has been connected
        saved = self.ctx.secrets.get(SECRET_KEY) or {}
        if not saved.get("refresh_token"):
            return None
        self._client = Client(saved["app_key"], saved["refresh_token"], self._http)
        return self._client

    # ---------- finding videos ----------
    def _candidates(self, s: Session) -> list[tuple[Path, int | None, str]]:
        """Finished page videos, then .mp4 files in the save folder: (file, output id, name in Dropbox)."""
        out = []
        for o in s.scalars(select(ClipOutput).where(ClipOutput.render_state == "ready", ClipOutput.file_path.is_not(None),
                                                    ClipOutput.status.not_in(("expired", "withdrawn")))).unique():
            p = Path(o.file_path)
            out.append((p, o.id, safe_name(p.parent.name)))
        folder = save_folder(load_settings(s))
        try:
            out += [(p, None, safe_name(p.stem)) for p in sorted(folder.glob("*.mp4"))]
        except OSError:
            pass
        return out

    def _queue(self, s: Session, since: datetime | None) -> int:
        known = set(s.scalars(select(DropboxUpload.local_path)))
        added = 0
        for p, oid, name in self._candidates(s):
            if str(p) in known:
                continue
            try:
                if since and datetime.fromtimestamp(p.stat().st_mtime, timezone.utc) < since:
                    continue  # made before Dropbox was connected: Sync all sends those
            except OSError:
                continue
            s.add(DropboxUpload(local_path=str(p), output_id=oid, name=name, status="queued"))
            known.add(str(p))
            added += 1
        return added

    def sync_all(self) -> int:
        """Queue every video on this computer that isn't in Dropbox yet, and retry the ones that failed."""
        with self.ctx.db.session() as s:
            n = self._queue(s, None)
            for r in s.scalars(select(DropboxUpload).where(DropboxUpload.status == "failed")):
                r.status, r.next_try_at, r.attempts = "queued", None, 0
                n += 1
            audit(s, "dropbox.sync_all", "dropbox", "", {"queued": n})
        self.wake()
        return n

    def retry(self, uid: int) -> bool:
        with self.ctx.db.session() as s:
            r = s.get(DropboxUpload, uid)
            if not r or r.status not in ("failed", "queued"):
                return False
            r.status, r.next_try_at, r.attempts, r.error = "queued", None, 0, None
        self.wake()
        return True

    def _stable(self, p: Path) -> bool:
        try:
            st = p.stat()
        except OSError:
            return False
        seen = self._seen.get(str(p))
        now = time.monotonic()
        if not seen or seen[:2] != (st.st_size, st.st_mtime):
            self._seen[str(p)] = (st.st_size, st.st_mtime, now)
            return False
        return st.st_size > 0 and now - seen[2] >= STABLE_SECONDS and time.time() - st.st_mtime >= STABLE_SECONDS

    # ---------- the loop ----------
    def tick(self) -> bool:
        """One step: look for new videos now and then, then upload the next one that's ready. True if it uploaded."""
        with self.ctx.db.session() as s:
            cfg, st = load_settings(s).dropbox, state(s)
            if cfg.auto_upload and st.get("connected") and time.monotonic() - self._scanned >= SCAN_EVERY:
                self._scanned = time.monotonic()
                self._queue(s, datetime.fromisoformat(st["since"]) if st.get("since") else None)
            due = datetime.now(timezone.utc)
            waiting = (DropboxUpload.status == "queued") | ((DropboxUpload.status == "failed") & DropboxUpload.next_try_at.is_not(None))
            rows = [(r.id, r.local_path) for r in s.scalars(select(DropboxUpload).where(waiting)
                                                            .order_by(DropboxUpload.output_id.is_(None), DropboxUpload.id))
                    if not r.next_try_at or r.next_try_at <= due]
            for uid, path in rows:  # a file that's gone can't be uploaded: say so, don't retry
                if not Path(path).exists():
                    r = s.get(DropboxUpload, uid)
                    r.status, r.error, r.next_try_at = "failed", "The file is no longer on this computer (it expired or was re-rendered).", None
            rows = [(uid, path) for uid, path in rows if Path(path).exists()]
        if not rows:
            return False
        client = self._get_client()
        if not client or not net.online():
            return False  # they wait in the queue until Dropbox is connected and the internet is back
        for uid, path in rows:
            if self._stable(Path(path)):
                self._upload(uid, client, cfg.folder)
                return True
        return False

    def _upload(self, uid: int, client: Client, folder: str) -> None:
        with self.ctx.db.session() as s:
            r = s.get(DropboxUpload, uid)
            r.status, r.error = "uploading", None
            path, name, session_id, offset, old_hash, target = Path(r.local_path), r.name, r.session_id, r.session_offset, r.content_hash, r.dropbox_path
        try:
            size, digest = path.stat().st_size, content_hash(path)
            with self.ctx.db.session() as s:
                r = s.get(DropboxUpload, uid)
                r.size_bytes, r.content_hash = size, digest
                twin = s.scalar(select(DropboxUpload).where(DropboxUpload.content_hash == digest, DropboxUpload.status == "uploaded",
                                                            DropboxUpload.size_bytes == size, DropboxUpload.id != uid).limit(1))
                if twin:  # a copy of a video that's already up (a saved copy): nothing to send
                    self._done(s, r, twin.dropbox_path, "same file")
                    return
            if digest != old_hash or not target:
                session_id, offset = None, 0  # the file changed, or nothing was started: start over
            if not session_id:
                target, already = self._free_path(client, folder, name, size, digest)
                if already:
                    with self.ctx.db.session() as s:
                        self._done(s, s.get(DropboxUpload, uid), target, "already in Dropbox")
                    return
            meta = self._send(uid, client, path, size, session_id, offset, target)
            check = client.metadata(target)
            if not check or check.get("size") != size or check.get("content_hash") != digest or meta.get("content_hash") != digest:
                if check:
                    client.delete(target)  # Vyral's own upload that came out wrong: never left in Dropbox
                raise DropboxError("The copy in Dropbox didn't match the file on this computer, so it was deleted and will be sent again.")
            with self.ctx.db.session() as s:
                self._done(s, s.get(DropboxUpload, uid), target, "uploaded")
            log.info("uploaded %s to Dropbox (%d bytes, verified)", path.name, size)
        except AuthError as e:
            self._client = None
            with self.ctx.db.session() as s:
                _save_state(s, needs_reconnect=True, error=str(e))
                s.get(DropboxUpload, uid).status = "queued"  # waits for Dropbox to be connected again
        except (DropboxError, httpx.HTTPError, OSError) as e:
            msg = str(e) if isinstance(e, DropboxError) else "The connection to Dropbox dropped." if isinstance(e, httpx.TransportError) \
                else f"Dropbox upload failed ({type(e).__name__})"
            with self.ctx.db.session() as s:
                r = s.get(DropboxUpload, uid)
                if isinstance(e, ApiError) and (_correct_offset(e.error) is None or "conflict" in e.summary):
                    r.session_id, r.session_offset = None, 0  # the session is unusable (expired, or the name got taken): start over
                r.attempts = tries = r.attempts + 1
                wait = min(30 * 2 ** (tries - 1), 3600)
                r.status, r.error, r.next_try_at = "failed", f"{msg} Trying again by itself.", datetime.now(timezone.utc) + timedelta(seconds=wait)
            log.warning("Dropbox upload of %s failed (try %d): %s", path.name, tries, msg)

    def _done(self, s: Session, r: DropboxUpload, dropbox_path: str, how: str) -> None:
        r.status, r.dropbox_path, r.error, r.next_try_at, r.attempts = "uploaded", dropbox_path, None, None, 0
        r.session_id, r.session_offset, r.uploaded_at = None, 0, datetime.now(timezone.utc)
        audit(s, "dropbox.uploaded", "output", r.output_id or "", {"path": dropbox_path, "how": how})

    @staticmethod
    def _free_path(client: Client, folder: str, name: str, size: int, digest: str) -> tuple[str, bool]:
        """The name to upload to, and whether that exact file is already there."""
        root = folder.rstrip("/")
        for n in range(1, 1000):
            path = f"{root}/{name}.mp4" if n == 1 else f"{root}/{name}-{n}.mp4"
            m = client.metadata(path)
            if m is None:
                return path, False
            if m.get(".tag") == "file" and m.get("size") == size and m.get("content_hash") == digest:
                return path, True
        raise DropboxError(f"Too many files named {name} in {folder}")

    def _progress(self, uid: int, session_id: str | None, offset: int, target: str) -> None:
        with self.ctx.db.session() as s:
            r = s.get(DropboxUpload, uid)
            r.session_id, r.session_offset, r.dropbox_path = session_id, offset, target

    def _send(self, uid: int, client: Client, path: Path, size: int, session_id: str | None, offset: int, target: str) -> dict:
        """The file's bytes as they are, piece by piece, carrying on from where Dropbox has them."""
        with open(path, "rb") as f:
            if not session_id:
                first = f.read(CHUNK)
                session_id, offset = client.start(first), len(first)
                self._progress(uid, session_id, offset, target)
            while offset < size and not self._stop.is_set():
                f.seek(offset)
                piece = f.read(CHUNK)
                try:
                    client.append(session_id, offset, piece)
                except ApiError as e:
                    right = _correct_offset(e.error)
                    if right is None:
                        raise
                    offset = right  # Dropbox already had more (a reply lost in a dropout) or less: go from there
                    self._progress(uid, session_id, offset, target)
                    continue
                offset += len(piece)
                self._progress(uid, session_id, offset, target)
            if offset < size:
                raise DropboxError("Vyral was closing; the upload carries on from here next time.")
            try:
                return client.finish(session_id, offset, target)
            except ApiError as e:
                right = _correct_offset(e.error)
                if right is not None:
                    self._progress(uid, session_id, right, target)
                raise

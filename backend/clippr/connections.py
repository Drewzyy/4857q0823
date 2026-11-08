"""Account connection service.

Owns the full OAuth lifecycle so the UI only ever shows "Connect" and the platform's own
login page: PKCE + state generation, the loopback callback, code exchange, identity lookup,
creating destination/source accounts, token storage in the keychain, refresh and revoke.
"""
from __future__ import annotations

import json
import logging
import secrets
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

import httpx
from sqlalchemy import select

from .audit import audit
from .models import Connection, DestinationAccount, Setting, SourceAccount
from .platforms import CONNECTORS
from .platforms.base import AppCredentials, OAuthConnector, PlatformError, TokenSet, new_pkce_verifier
from .schemas import default_destination_settings

log = logging.getLogger("clippr.connections")
ATTEMPT_TTL = 15 * 60
MAX_PENDING = 20
APP_META_KEY = "platform_apps"


@dataclass
class Attempt:
    id: str
    platform: str
    purpose: str
    redirect_uri: str
    verifier: str | None
    link_destination_id: int | None
    created: float = field(default_factory=time.time)
    status: str = "pending"  # pending | succeeded | failed
    message: str = ""
    connection_id: int | None = None
    accounts_added: int = 0

    def public(self) -> dict[str, Any]:
        return {"id": self.id, "platform": self.platform, "purpose": self.purpose, "status": self.status,
                "message": self.message, "connection_id": self.connection_id, "accounts_added": self.accounts_added}


class ConnectionService:
    def __init__(self, ctx: Any, http_factory: Callable[[], httpx.Client] | None = None):
        self.ctx = ctx
        self._attempts: dict[str, Attempt] = {}
        self._lock = threading.Lock()
        self._http_factory = http_factory or (lambda: httpx.Client(timeout=20.0, follow_redirects=False))

    # ---------- developer app credentials ----------
    def connector(self, key: str) -> OAuthConnector:
        c = CONNECTORS.get(key)
        if not c:
            raise PlatformError(f"Unknown platform '{key}'", code="unknown_platform")
        return c

    def _app_meta(self, s) -> dict[str, Any]:
        row = s.get(Setting, APP_META_KEY)
        return dict(row.value) if row else {}

    def _save_app_meta(self, s, meta: dict[str, Any]) -> None:
        row = s.get(Setting, APP_META_KEY)
        if row:
            row.value = meta
        else:
            s.add(Setting(key=APP_META_KEY, value=meta))

    def app_credentials(self, key: str) -> AppCredentials | None:
        stored = self.ctx.secrets.get(f"app:{key}")
        if stored and stored.get("client_id"):
            return AppCredentials(stored["client_id"], stored.get("client_secret", ""))
        bundled = self.ctx.bundled_apps.get(key)
        if bundled and bundled.get("client_id"):
            return AppCredentials(bundled["client_id"], bundled.get("client_secret", ""))
        return None

    def redirect_uri(self, key: str) -> str:
        stored = self.ctx.secrets.get(f"app:{key}") or {}
        return stored.get("redirect_uri") or self.connector(key).redirect_uri(self.ctx.config.base_url)

    def set_app_credentials(self, key: str, client_id: str, client_secret: str, redirect_uri: str | None = None) -> dict[str, Any]:
        conn = self.connector(key)
        client_id, client_secret = client_id.strip(), client_secret.strip()
        if not client_id or not client_secret or len(client_id) > 300 or len(client_secret) > 300:
            raise PlatformError("Both fields are required", code="validation")
        redirect_uri = (redirect_uri or "").strip() or None
        if redirect_uri:
            from urllib.parse import urlparse

            u = urlparse(redirect_uri)
            if key != "meta" or u.scheme != "https" or not u.netloc or u.query or u.fragment or len(redirect_uri) > 300:
                raise PlatformError("A custom redirect must be a plain https:// URL (Facebook & Instagram only).", code="validation")
        app = AppCredentials(client_id, client_secret)
        with self._http_factory() as http:
            try:
                conn.validate_app(http, app, conn.redirect_uri(self.ctx.config.base_url))
            except httpx.HTTPError:
                raise PlatformError(f"Couldn't reach {conn.label} to check the credentials. Check your internet connection and try again.", code="network")
        record = {"client_id": client_id, "client_secret": client_secret}
        if redirect_uri:
            record["redirect_uri"] = redirect_uri
        self.ctx.secrets.set(f"app:{key}", record)
        with self.ctx.db.session() as s:
            meta = self._app_meta(s)
            meta[key] = {"validated_at": datetime.now(timezone.utc).isoformat(), "client_id_hint": client_id[:6] + "…" + client_id[-4:],
                         "redirect_uri": redirect_uri}
            self._save_app_meta(s, meta)
            audit(s, "platform_app.configured", "platform", key)
        return self.platform_status(key)

    def import_google_client_json(self, text: str) -> dict[str, Any]:
        try:
            data = json.loads(text)
        except ValueError:
            raise PlatformError("That file isn't valid JSON. Use the file Google offers when you create the OAuth client.", code="validation")
        block = data.get("installed") or data.get("web") or {}
        if "web" in data and "installed" not in data:
            raise PlatformError("This is a 'Web application' client. Create a 'Desktop app' client instead so no redirect setup is needed.", code="validation")
        if not block.get("client_id") or not block.get("client_secret"):
            raise PlatformError("The file doesn't contain a client_id and client_secret.", code="validation")
        return self.set_app_credentials("youtube", block["client_id"], block["client_secret"])

    def remove_app_credentials(self, key: str) -> None:
        self.connector(key)
        self.ctx.secrets.delete(f"app:{key}")
        with self.ctx.db.session() as s:
            meta = self._app_meta(s)
            meta.pop(key, None)
            self._save_app_meta(s, meta)
            audit(s, "platform_app.removed", "platform", key)

    def platform_status(self, key: str | None = None) -> Any:
        base = self.ctx.config.base_url
        with self.ctx.db.session() as s:
            meta = self._app_meta(s)
            counts = {k: s.query(Connection).filter(Connection.platform == k).count() for k in CONNECTORS}
        out = []
        for k, c in CONNECTORS.items():
            if key and k != key:
                continue
            configured = self.app_credentials(k) is not None
            out.append({
                "key": k, "label": c.label, "configured": configured,
                "source": "bundled" if configured and k in self.ctx.bundled_apps and k not in meta else "user",
                "validated_at": (meta.get(k) or {}).get("validated_at"),
                "client_id_hint": (meta.get(k) or {}).get("client_id_hint"),
                "destination_platforms": list(c.destination_platforms), "supports_source": c.supports_source,
                "redirect_uri": (meta.get(k) or {}).get("redirect_uri") or c.registered_redirect_uri(base),
                "custom_redirect": bool((meta.get(k) or {}).get("redirect_uri")),
                "credential_fields": [vars(f) for f in c.credential_fields],
                "setup_steps": [vars(st) for st in c.setup_steps(c.registered_redirect_uri(base))],
                "notes": c.notes, "connections": counts.get(k, 0),
            })
        return out[0] if key else out

    # ---------- authorization flow ----------
    def _prune(self) -> None:
        now = time.time()
        for k in [k for k, a in self._attempts.items() if now - a.created > ATTEMPT_TTL]:
            del self._attempts[k]

    def start(self, key: str, purpose: str = "destination", link_destination_id: int | None = None) -> tuple[Attempt, str]:
        conn = self.connector(key)
        if purpose not in ("destination", "source"):
            raise PlatformError("purpose must be destination or source", code="validation")
        if purpose == "source" and not conn.supports_source:
            raise PlatformError(f"{conn.label} can't be connected as a source yet", code="validation")
        app = self.app_credentials(key)
        if not app:
            raise PlatformError(f"{conn.label} needs a one-time setup before you can log in.", code="setup_required")
        with self._lock:
            self._prune()
            if sum(1 for a in self._attempts.values() if a.status == "pending") >= MAX_PENDING:
                raise PlatformError("Too many sign-in windows are open. Finish or close one and try again.", code="rate_limited")
            # Port prefix lets an optional HTTPS relay page bounce the browser back to this app.
            state = f"{self.ctx.config.port}.{secrets.token_urlsafe(24)}"
            verifier = new_pkce_verifier() if conn.uses_pkce else None
            attempt = Attempt(state, key, purpose, self.redirect_uri(key), verifier, link_destination_id)
            self._attempts[state] = attempt
        return attempt, conn.authorize_url(app, attempt.redirect_uri, state, verifier, purpose)

    def attempt(self, attempt_id: str) -> Attempt | None:
        with self._lock:
            self._prune()
            return self._attempts.get(attempt_id)

    def complete(self, key: str, params: dict[str, str]) -> Attempt:
        state = params.get("state", "")
        with self._lock:
            attempt = self._attempts.get(state)
            if not attempt or attempt.platform != key or attempt.status != "pending" or time.time() - attempt.created > ATTEMPT_TTL:
                raise PlatformError("This sign-in link is invalid or has expired. Start again from AI Clipper.", code="invalid_state")
            attempt.status = "processing"
        try:
            if params.get("error"):
                desc = params.get("error_description") or params.get("error_reason") or params["error"]
                if params["error"] in ("access_denied", "user_denied") or "denied" in desc.lower():
                    raise PlatformError("You cancelled the sign-in. Nothing was connected.", code="cancelled")
                raise PlatformError(f"The platform returned an error: {desc[:200]}")
            code = params.get("code")
            if not code:
                raise PlatformError("The platform didn't return an authorization code.")
            self._finish(attempt, code)
            attempt.status = "succeeded"
        except PlatformError as e:
            attempt.status, attempt.message = "failed", str(e)
        except httpx.HTTPError:
            attempt.status, attempt.message = "failed", "Couldn't reach the platform to finish signing in. Check your connection and try again."
        except Exception:
            log.exception("oauth completion failed for %s", key)
            attempt.status, attempt.message = "failed", "Something went wrong while saving the connection. Details are in the app log."
        return attempt

    def _finish(self, attempt: Attempt, code: str) -> None:
        conn = self.connector(attempt.platform)
        app = self.app_credentials(attempt.platform)
        if not app:
            raise PlatformError("Platform setup was removed during sign-in")
        with self._http_factory() as http:
            tokens = conn.exchange_code(http, app, code, attempt.redirect_uri, attempt.verifier)
            ident = conn.identities(http, app, tokens)
        with self.ctx.db.session() as s:
            row = s.scalar(select(Connection).where(Connection.platform == attempt.platform, Connection.external_user_id == ident.external_user_id))
            if not row:
                row = Connection(platform=attempt.platform, external_user_id=ident.external_user_id)
                s.add(row)
            row.display_name, row.avatar_url = ident.display_name, ident.avatar_url
            row.scopes, row.status, row.last_error = tokens.scopes, "connected", None
            row.access_expires_at, row.refresh_expires_at = tokens.access_expires_at(), tokens.refresh_expires_at()
            row.last_checked_at = datetime.now(timezone.utc)
            s.flush()
            self.ctx.secrets.set(row.secret_key, tokens.to_secret())
            added = 0
            if attempt.purpose == "destination":
                link_id = attempt.link_destination_id
                for acct in ident.accounts:
                    dest = s.scalar(select(DestinationAccount).where(DestinationAccount.platform == acct.platform, DestinationAccount.external_id == acct.external_id))
                    if not dest and link_id:
                        draft = s.get(DestinationAccount, link_id)
                        if draft and draft.platform == acct.platform and draft.external_id.startswith("draft:"):
                            dest, link_id = draft, None
                            dest.external_id = acct.external_id
                    if not dest:
                        dest = DestinationAccount(platform=acct.platform, external_id=acct.external_id, settings=default_destination_settings(acct.platform))
                        s.add(dest)
                        added += 1
                    dest.display_name, dest.handle, dest.avatar_url = acct.display_name, acct.handle, acct.avatar_url
                    dest.connection_id = row.id
                    if acct.secret:
                        self.ctx.secrets.set(f"account:{acct.platform}:{acct.external_id}", acct.secret)
            else:
                for acct in ident.accounts:
                    username = (acct.handle or acct.external_id).lower()
                    src = s.scalar(select(SourceAccount).where(SourceAccount.platform == acct.platform, SourceAccount.username == username))
                    if not src:
                        from .platforms.urls import profile_url

                        src = SourceAccount(platform=acct.platform, username=username, profile_url=profile_url(acct.platform, username) if acct.handle else "")
                        s.add(src)
                        added += 1
                    src.display_name, src.avatar_url, src.connection_id = acct.display_name, acct.avatar_url, row.id
            s.flush()
            audit(s, "connection.connected", "connection", row.id, {"platform": attempt.platform, "purpose": attempt.purpose, "accounts": len(ident.accounts)})
            attempt.connection_id, attempt.accounts_added = row.id, added
            attempt.message = f"Connected {ident.display_name}"

    # ---------- token lifecycle ----------
    def tokens(self, connection: Connection) -> dict[str, Any] | None:
        return self.ctx.secrets.get(connection.secret_key)

    def refresh(self, connection_id: int) -> str:
        """Refresh one connection's access token. Returns the resulting status."""
        with self.ctx.db.session() as s:
            row = s.get(Connection, connection_id)
            if not row:
                return "missing"
            conn = self.connector(row.platform)
            app = self.app_credentials(row.platform)
            stored = self.tokens(row) or {}
            if not app or not stored.get("refresh_token"):
                if row.access_expires_at and row.access_expires_at < datetime.now(timezone.utc):
                    row.status, row.last_error = "expired", "Sign in again to keep this account connected."
                elif row.access_expires_at and row.access_expires_at < datetime.now(timezone.utc) + timedelta(days=7):
                    row.status = "expiring"
                return row.status
            try:
                with self._http_factory() as http:
                    ts: TokenSet = conn.refresh(http, app, stored["refresh_token"])
                ts.extra = {**stored.get("extra", {}), **{k: v for k, v in ts.extra.items() if v}}
                self.ctx.secrets.set(row.secret_key, ts.to_secret())
                row.access_expires_at = ts.access_expires_at()
                if ts.refresh_expires_in:
                    row.refresh_expires_at = ts.refresh_expires_at()
                row.status, row.last_error = "connected", None
            except PlatformError as e:
                row.status, row.last_error = ("expired" if e.reauth else "error"), str(e)
            row.last_checked_at = datetime.now(timezone.utc)
            audit(s, "connection.refreshed", "connection", row.id, {"status": row.status})
            return row.status

    def refresh_due(self) -> dict[str, int]:
        soon = datetime.now(timezone.utc) + timedelta(minutes=15)
        week = datetime.now(timezone.utc) + timedelta(days=7)
        with self.ctx.db.session() as s:
            ids = [c.id for c in s.scalars(select(Connection).where(Connection.status.in_(("connected", "expiring", "error"))))
                   if c.access_expires_at and (c.access_expires_at < soon or (c.platform == "meta" and c.access_expires_at < week))]
        results: dict[str, int] = {}
        for cid in ids:
            st = self.refresh(cid)
            results[st] = results.get(st, 0) + 1
        return results

    def disconnect(self, connection_id: int) -> None:
        with self.ctx.db.session() as s:
            row = s.get(Connection, connection_id)
            if not row:
                raise PlatformError("Connection not found", code="not_found")
            conn = self.connector(row.platform)
            app = self.app_credentials(row.platform)
            stored = self.tokens(row) or {}
            if app and stored.get("access_token"):
                try:
                    with self._http_factory() as http:
                        conn.revoke(http, app, stored["access_token"])
                except httpx.HTTPError:
                    pass  # local removal still happens; the platform token simply expires
            for d in s.scalars(select(DestinationAccount).where(DestinationAccount.connection_id == row.id)):
                self.ctx.secrets.delete(f"account:{d.platform}:{d.external_id}")
            self.ctx.secrets.delete(row.secret_key)
            audit(s, "connection.disconnected", "connection", row.id, {"platform": row.platform})
            s.delete(row)  # destinations/sources keep their settings; FK becomes NULL


CALLBACK_PAGE = """<!doctype html><html lang="en"><head><meta charset="utf-8"><title>AI Clipper</title>
<meta name="viewport" content="width=device-width,initial-scale=1">
<style>body{{margin:0;min-height:100vh;display:grid;place-items:center;background:#0e0e11;color:#f4f4f6;
font:16px -apple-system,BlinkMacSystemFont,"SF Pro Text","Segoe UI",sans-serif}}
.c{{max-width:420px;padding:32px;border-radius:16px;background:#18181c;text-align:center}}
h1{{font-size:20px;margin:0 0 8px}}p{{color:#a1a1aa;margin:0;line-height:1.5}}
.i{{width:44px;height:44px;border-radius:50%;margin:0 auto 16px;display:grid;place-items:center;font-size:22px;background:{color}}}</style>
</head><body><div class="c"><div class="i">{icon}</div><h1>{title}</h1><p>{message}</p></div>
<script>setTimeout(function(){{window.close()}},2500)</script></body></html>"""

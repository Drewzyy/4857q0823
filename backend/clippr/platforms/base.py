"""Common types for platform connectors.

A connector wraps one official OAuth 2.0 authorization flow plus the identity lookups needed
to turn a login into destination/source accounts. Publishing and analytics adapters plug in
on the same classes in later milestones.
"""
from __future__ import annotations

import base64
import hashlib
import secrets
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx


class PlatformError(Exception):
    """Error safe to show to the user (never contains secrets)."""

    def __init__(self, message: str, *, code: str = "platform_error", reauth: bool = False):
        super().__init__(message)
        self.code = code
        self.reauth = reauth


@dataclass
class AppCredentials:
    client_id: str
    client_secret: str


@dataclass
class TokenSet:
    access_token: str
    refresh_token: str | None = None
    expires_in: int | None = None
    refresh_expires_in: int | None = None
    scopes: list[str] = field(default_factory=list)
    extra: dict[str, Any] = field(default_factory=dict)

    def to_secret(self) -> dict[str, Any]:
        now = datetime.now(timezone.utc)
        return {
            "access_token": self.access_token,
            "refresh_token": self.refresh_token,
            "access_expires_at": (now + timedelta(seconds=self.expires_in)).isoformat() if self.expires_in else None,
            "extra": self.extra,
        }

    def access_expires_at(self) -> datetime | None:
        return datetime.now(timezone.utc) + timedelta(seconds=self.expires_in) if self.expires_in else None

    def refresh_expires_at(self) -> datetime | None:
        return datetime.now(timezone.utc) + timedelta(seconds=self.refresh_expires_in) if self.refresh_expires_in else None


@dataclass
class AccountIdentity:
    """A publishable account discovered through a login (channel, page, IG account...)."""

    platform: str  # destination platform: youtube | tiktok | facebook | instagram
    external_id: str
    display_name: str
    handle: str = ""
    avatar_url: str | None = None
    secret: dict[str, Any] | None = None  # e.g. a Facebook Page access token


@dataclass
class ConnectedIdentity:
    external_user_id: str
    display_name: str
    avatar_url: str | None
    accounts: list[AccountIdentity]


@dataclass
class SetupStep:
    title: str
    detail: str
    url: str | None = None
    copy_value: str | None = None


@dataclass
class CredentialField:
    name: str
    label: str
    secret: bool = False
    placeholder: str = ""


def new_pkce_verifier() -> str:
    return secrets.token_urlsafe(64)[:96]


def pkce_challenge_b64(verifier: str) -> str:
    return base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()


def pkce_challenge_hex(verifier: str) -> str:
    # TikTok's desktop flow expects a hex digest, not base64url.
    return hashlib.sha256(verifier.encode()).hexdigest()


class OAuthConnector:
    key: str = ""
    label: str = ""
    destination_platforms: tuple[str, ...] = ()
    supports_source: bool = False
    uses_pkce: bool = True
    credential_fields: list[CredentialField] = []
    notes: list[str] = []

    def callback_path(self) -> str:
        return f"/oauth/callback/{self.key}"

    def setup_steps(self, redirect_uri: str) -> list[SetupStep]:
        raise NotImplementedError

    def redirect_uri(self, base_url: str) -> str:
        """The concrete redirect sent in the authorize request."""
        return base_url + self.callback_path()

    def registered_redirect_uri(self, base_url: str) -> str:
        """What the user registers in the developer console (may contain a wildcard)."""
        return base_url + self.callback_path()

    def authorize_url(self, app: AppCredentials, redirect_uri: str, state: str, verifier: str | None, purpose: str) -> str:
        raise NotImplementedError

    def exchange_code(self, http: httpx.Client, app: AppCredentials, code: str, redirect_uri: str, verifier: str | None) -> TokenSet:
        raise NotImplementedError

    def refresh(self, http: httpx.Client, app: AppCredentials, refresh_token: str) -> TokenSet:
        raise PlatformError(f"{self.label} logins can't be refreshed automatically. Reconnect the account.", code="reauth_required", reauth=True)

    def identities(self, http: httpx.Client, app: AppCredentials, tokens: TokenSet) -> ConnectedIdentity:
        raise NotImplementedError

    def validate_app(self, http: httpx.Client, app: AppCredentials, redirect_uri: str) -> None:
        """Raise PlatformError if the developer credentials are rejected."""
        raise NotImplementedError

    def revoke(self, http: httpx.Client, app: AppCredentials, access_token: str) -> None:
        return None


def json_or_error(resp: httpx.Response, label: str) -> dict[str, Any]:
    try:
        data = resp.json()
    except ValueError:
        raise PlatformError(f"{label} returned an unexpected response (HTTP {resp.status_code})")
    if not isinstance(data, dict):
        raise PlatformError(f"{label} returned an unexpected response")
    return data

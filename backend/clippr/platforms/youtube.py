"""YouTube (Google OAuth 2.0 for installed apps, loopback redirect + PKCE)."""
from __future__ import annotations

from urllib.parse import urlencode

import httpx

from .base import (
    AccountIdentity,
    AppCredentials,
    ConnectedIdentity,
    CredentialField,
    OAuthConnector,
    PlatformError,
    SetupStep,
    TokenSet,
    json_or_error,
    pkce_challenge_b64,
)

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
REVOKE_URL = "https://oauth2.googleapis.com/revoke"
CHANNELS_URL = "https://www.googleapis.com/youtube/v3/channels"
SCOPES = [
    "https://www.googleapis.com/auth/youtube.upload",
    "https://www.googleapis.com/auth/youtube.readonly",
]


def _token_error(data: dict, label: str = "Google") -> PlatformError:
    err = data.get("error", "unknown_error")
    desc = data.get("error_description", "")
    if err == "invalid_grant":
        return PlatformError("Google says this login has expired or was revoked. Reconnect the account.", code="reauth_required", reauth=True)
    if err in ("invalid_client", "unauthorized_client"):
        return PlatformError("Google rejected the app's Client ID or Client secret.", code="invalid_client")
    return PlatformError(f"{label} sign-in failed: {err} {desc}".strip())


class YouTubeConnector(OAuthConnector):
    key = "youtube"
    label = "YouTube"
    destination_platforms = ("youtube",)
    credential_fields = [
        CredentialField("client_id", "Client ID", placeholder="1234-abc.apps.googleusercontent.com"),
        CredentialField("client_secret", "Client secret", secret=True),
    ]
    notes = [
        "While the Google app is in 'Testing', Google expires the login after 7 days; AI Clipper will ask you to sign in again. Publishing the app (no review needed for a personal tool with you as the only user) removes that limit.",
        "Videos uploaded through an unverified Google project are locked to private until the project passes Google's API audit.",
    ]

    def setup_steps(self, redirect_uri: str) -> list[SetupStep]:
        return [
            SetupStep("Create a Google Cloud project", "Any name works, for example 'AI Clipper'.", "https://console.cloud.google.com/projectcreate"),
            SetupStep("Turn on the YouTube Data API v3", "Click Enable.", "https://console.cloud.google.com/apis/library/youtube.googleapis.com"),
            SetupStep("Set up the consent screen", "Choose External, fill in the app name and your email, then add your own Google account under Audience > Test users.", "https://console.cloud.google.com/auth/overview"),
            SetupStep("Create an OAuth client", "Application type: Desktop app. No redirect URL is needed for desktop clients. Download the JSON file when it's created.", "https://console.cloud.google.com/auth/clients/create"),
            SetupStep("Drop the downloaded JSON file here", "Or paste the Client ID and secret below. AI Clipper checks them with Google immediately."),
        ]

    def authorize_url(self, app, redirect_uri, state, verifier, purpose):
        q = {
            "client_id": app.client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            "scope": " ".join(SCOPES),
            "state": state,
            "access_type": "offline",
            "prompt": "consent select_account",
            "include_granted_scopes": "true",
            "code_challenge": pkce_challenge_b64(verifier or ""),
            "code_challenge_method": "S256",
        }
        return f"{AUTH_URL}?{urlencode(q)}"

    def _tokens(self, data: dict) -> TokenSet:
        if "access_token" not in data:
            raise _token_error(data)
        return TokenSet(
            access_token=data["access_token"],
            refresh_token=data.get("refresh_token"),
            expires_in=data.get("expires_in"),
            refresh_expires_in=data.get("refresh_token_expires_in"),
            scopes=(data.get("scope") or "").split(),
        )

    def exchange_code(self, http, app, code, redirect_uri, verifier):
        r = http.post(TOKEN_URL, data={
            "code": code, "client_id": app.client_id, "client_secret": app.client_secret,
            "redirect_uri": redirect_uri, "grant_type": "authorization_code", "code_verifier": verifier or "",
        })
        return self._tokens(json_or_error(r, "Google"))

    def refresh(self, http, app, refresh_token):
        r = http.post(TOKEN_URL, data={
            "client_id": app.client_id, "client_secret": app.client_secret,
            "refresh_token": refresh_token, "grant_type": "refresh_token",
        })
        ts = self._tokens(json_or_error(r, "Google"))
        ts.refresh_token = ts.refresh_token or refresh_token
        return ts

    def identities(self, http, app, tokens):
        r = http.get(CHANNELS_URL, params={"part": "snippet", "mine": "true", "maxResults": 50},
                     headers={"Authorization": f"Bearer {tokens.access_token}"})
        data = json_or_error(r, "YouTube")
        if r.status_code >= 400:
            msg = data.get("error", {}).get("message", f"HTTP {r.status_code}")
            raise PlatformError(f"YouTube refused to list your channels: {msg}")
        items = data.get("items") or []
        if not items:
            raise PlatformError("This Google account has no YouTube channel. Create one at youtube.com, then connect again.", code="no_channel")
        accounts = []
        for it in items:
            sn = it.get("snippet", {})
            thumb = (sn.get("thumbnails", {}).get("default") or {}).get("url")
            accounts.append(AccountIdentity("youtube", it["id"], sn.get("title", it["id"]), sn.get("customUrl", ""), thumb))
        first = accounts[0]
        return ConnectedIdentity(first.external_id, first.display_name, first.avatar_url, accounts)

    def validate_app(self, http, app, redirect_uri):
        # A deliberately invalid code: Google answers invalid_grant for a real client and
        # invalid_client for a bad ID/secret. Nothing is authorised by this call.
        r = http.post(TOKEN_URL, data={
            "code": "ai-clipper-credential-check", "client_id": app.client_id, "client_secret": app.client_secret,
            "redirect_uri": redirect_uri, "grant_type": "authorization_code",
        })
        data = json_or_error(r, "Google")
        if data.get("error") in ("invalid_client", "unauthorized_client"):
            raise PlatformError("Google rejected this Client ID / secret. Check you copied the Desktop app client.", code="invalid_client")
        if data.get("error") not in ("invalid_grant", "invalid_request", "redirect_uri_mismatch"):
            raise PlatformError(f"Unexpected answer from Google: {data.get('error', 'unknown')}")

    def revoke(self, http, app, access_token):
        http.post(REVOKE_URL, params={"token": access_token})

"""TikTok Login Kit for Desktop (loopback redirect, PKCE with hex challenge) + Display API identity."""
from __future__ import annotations

from urllib.parse import urlencode


from .base import (
    AccountIdentity,
    ConnectedIdentity,
    CredentialField,
    OAuthConnector,
    PlatformError,
    SetupStep,
    TokenSet,
    json_or_error,
    pkce_challenge_hex,
)

AUTH_URL = "https://www.tiktok.com/v2/auth/authorize/"
TOKEN_URL = "https://open.tiktokapis.com/v2/oauth/token/"
REVOKE_URL = "https://open.tiktokapis.com/v2/oauth/revoke/"
USER_URL = "https://open.tiktokapis.com/v2/user/info/"

# Scopes differ by purpose: monitoring an account you own needs read scopes, publishing needs post scopes.
SCOPES = {
    "source": ["user.info.basic", "user.info.profile", "user.info.stats", "video.list"],
    "destination": ["user.info.basic", "user.info.profile", "user.info.stats", "video.list", "video.publish", "video.upload"],
}


def _token_error(data: dict) -> PlatformError:
    err = data.get("error", "unknown_error")
    if err in ("invalid_grant",):
        return PlatformError("TikTok says this login expired or was revoked. Reconnect the account.", code="reauth_required", reauth=True)
    if err in ("invalid_client", "unauthorized_client"):
        return PlatformError("TikTok rejected the app's Client key or Client secret.", code="invalid_client")
    return PlatformError(f"TikTok sign-in failed: {err} {data.get('error_description', '')}".strip())


class TikTokConnector(OAuthConnector):
    key = "tiktok"
    label = "TikTok"
    destination_platforms = ("tiktok",)
    supports_source = True
    credential_fields = [
        CredentialField("client_id", "Client key"),
        CredentialField("client_secret", "Client secret", secret=True),
    ]
    notes = [
        "Until TikTok audits your app, posts made through it are forced to private (SELF_ONLY) and the posting account must be private. You can still review them and make them public in the TikTok app.",
        "TikTok's API does not expose who you follow, and only returns videos for accounts that log in. Accounts you don't own are added by username or link.",
    ]

    def registered_redirect_uri(self, base_url: str) -> str:
        # TikTok desktop apps accept a wildcard port, so the registration survives port changes.
        return f"http://127.0.0.1:*{self.callback_path()}/"

    def redirect_uri(self, base_url: str) -> str:
        return f"{base_url}{self.callback_path()}/"

    def setup_steps(self, redirect_uri: str) -> list[SetupStep]:
        return [
            SetupStep("Open TikTok for Developers and create an app", "Log in with any TikTok account, then Manage apps > Connect an app.", "https://developers.tiktok.com/apps/"),
            SetupStep("Add the Login Kit product", "Under Login Kit, open the Desktop tab and add this redirect URI.", None, redirect_uri),
            SetupStep("Add the Content Posting API product", "Enable Direct Post. This is what lets Vyral upload clips."),
            SetupStep("Add these scopes", "Under Scopes, tick each of these.", None, "user.info.basic, user.info.profile, user.info.stats, video.list, video.upload, video.publish"),
            SetupStep("Paste the Client key and Client secret below", "They're on the app's Credentials panel. Vyral checks them with TikTok immediately."),
        ]

    def authorize_url(self, app, redirect_uri, state, verifier, purpose):
        q = {
            "client_key": app.client_id,
            "scope": ",".join(SCOPES.get(purpose, SCOPES["destination"])),
            "response_type": "code",
            "redirect_uri": redirect_uri,
            "state": state,
            "code_challenge": pkce_challenge_hex(verifier or ""),
            "code_challenge_method": "S256",
            "disable_auto_auth": "1",
        }
        return f"{AUTH_URL}?{urlencode(q)}"

    def _tokens(self, data: dict) -> TokenSet:
        if "access_token" not in data:
            raise _token_error(data)
        return TokenSet(
            access_token=data["access_token"],
            refresh_token=data.get("refresh_token"),
            expires_in=data.get("expires_in"),
            refresh_expires_in=data.get("refresh_expires_in"),
            scopes=[s for s in (data.get("scope") or "").split(",") if s],
            extra={"open_id": data.get("open_id")},
        )

    def exchange_code(self, http, app, code, redirect_uri, verifier):
        r = http.post(TOKEN_URL, data={
            "client_key": app.client_id, "client_secret": app.client_secret, "code": code,
            "grant_type": "authorization_code", "redirect_uri": redirect_uri, "code_verifier": verifier or "",
        }, headers={"Content-Type": "application/x-www-form-urlencoded"})
        return self._tokens(json_or_error(r, "TikTok"))

    def refresh(self, http, app, refresh_token):
        r = http.post(TOKEN_URL, data={
            "client_key": app.client_id, "client_secret": app.client_secret,
            "grant_type": "refresh_token", "refresh_token": refresh_token,
        }, headers={"Content-Type": "application/x-www-form-urlencoded"})
        return self._tokens(json_or_error(r, "TikTok"))

    def identities(self, http, app, tokens):
        fields = ["open_id", "avatar_url", "display_name"]
        if "user.info.profile" in tokens.scopes:
            fields.append("username")
        r = http.get(USER_URL, params={"fields": ",".join(fields)}, headers={"Authorization": f"Bearer {tokens.access_token}"})
        data = json_or_error(r, "TikTok")
        err = data.get("error") or {}
        if err.get("code") not in (None, "ok"):
            raise PlatformError(f"TikTok refused the profile lookup: {err.get('message') or err.get('code')}")
        user = (data.get("data") or {}).get("user") or {}
        open_id = user.get("open_id") or tokens.extra.get("open_id")
        if not open_id:
            raise PlatformError("TikTok did not return an account ID")
        name = user.get("display_name") or user.get("username") or "TikTok account"
        acct = AccountIdentity("tiktok", open_id, name, user.get("username", ""), user.get("avatar_url"))
        return ConnectedIdentity(open_id, name, acct.avatar_url, [acct])

    def validate_app(self, http, app, redirect_uri):
        # client_credentials returns an app-level token for a valid key/secret pair; it grants no user access.
        r = http.post(TOKEN_URL, data={"client_key": app.client_id, "client_secret": app.client_secret, "grant_type": "client_credentials"},
                      headers={"Content-Type": "application/x-www-form-urlencoded"})
        data = json_or_error(r, "TikTok")
        if "access_token" not in data:
            raise PlatformError("TikTok rejected this Client key / secret.", code="invalid_client")

    def revoke(self, http, app, access_token):
        http.post(REVOKE_URL, data={"client_key": app.client_id, "client_secret": app.client_secret, "token": access_token},
                  headers={"Content-Type": "application/x-www-form-urlencoded"})

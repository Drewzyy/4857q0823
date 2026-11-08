"""Facebook Login: one login connects every Facebook Page you manage and the Instagram
professional accounts linked to them."""
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
)

GRAPH_VERSION = "v23.0"
DIALOG_URL = f"https://www.facebook.com/{GRAPH_VERSION}/dialog/oauth"
GRAPH = f"https://graph.facebook.com/{GRAPH_VERSION}"
SCOPES = [
    "pages_show_list",
    "pages_read_engagement",
    "pages_manage_posts",
    "instagram_basic",
    "instagram_content_publish",
    "instagram_manage_insights",
    "business_management",
]


def _graph_error(data: dict, what: str) -> PlatformError:
    err = data.get("error") or {}
    code = err.get("code")
    if code == 190:
        return PlatformError("Facebook says this login expired or was revoked. Reconnect the account.", code="reauth_required", reauth=True)
    if code == 101 or err.get("type") == "OAuthException" and "client" in (err.get("message") or "").lower():
        return PlatformError("Facebook rejected the App ID or App secret.", code="invalid_client")
    return PlatformError(f"Facebook {what} failed: {err.get('message', 'unknown error')}")


class MetaConnector(OAuthConnector):
    key = "meta"
    label = "Facebook & Instagram"
    destination_platforms = ("facebook", "instagram")
    uses_pkce = False  # state + server-side secret protect the exchange
    credential_fields = [
        CredentialField("client_id", "App ID"),
        CredentialField("client_secret", "App secret", secret=True),
    ]
    notes = [
        "Instagram publishing works for Business or Creator accounts that are linked to a Facebook Page.",
        "While the Meta app stays in Development mode, you (as the app's admin) can use every permission without App Review. Review is only needed if other people will log in.",
        "Meta logins last about 60 days. Vyral warns you a week before and asks you to sign in again.",
    ]

    def setup_steps(self, redirect_uri: str) -> list[SetupStep]:
        return [
            SetupStep("Create a Meta app", "Pick 'Other' then 'Business' (or the 'Manage everything on your Page' use case).", "https://developers.facebook.com/apps/creation/"),
            SetupStep("Add Facebook Login for Business", "In Settings, add this as a Valid OAuth Redirect URI. In Development mode localhost is accepted.", None, redirect_uri),
            SetupStep("Add the Instagram product", "Choose 'API setup with Facebook login' so linked Instagram accounts can publish."),
            SetupStep("If Meta rejects the localhost address", "Host relay/index.html from the Vyral folder on any HTTPS site (GitHub Pages is free), register that URL instead, and paste it under Advanced below."),
            SetupStep("Paste the App ID and App secret below", "They're under App settings > Basic. Vyral checks them with Meta immediately.", "https://developers.facebook.com/apps/"),
        ]

    def authorize_url(self, app, redirect_uri, state, verifier, purpose):
        q = {"client_id": app.client_id, "redirect_uri": redirect_uri, "state": state, "response_type": "code", "scope": ",".join(SCOPES)}
        return f"{DIALOG_URL}?{urlencode(q)}"

    def exchange_code(self, http, app, code, redirect_uri, verifier):
        r = http.get(f"{GRAPH}/oauth/access_token", params={
            "client_id": app.client_id, "client_secret": app.client_secret, "redirect_uri": redirect_uri, "code": code,
        })
        data = json_or_error(r, "Facebook")
        if "access_token" not in data:
            raise _graph_error(data, "sign-in")
        # Swap the short-lived token for a long-lived (~60 day) one.
        r2 = http.get(f"{GRAPH}/oauth/access_token", params={
            "grant_type": "fb_exchange_token", "client_id": app.client_id, "client_secret": app.client_secret,
            "fb_exchange_token": data["access_token"],
        })
        long = json_or_error(r2, "Facebook")
        if "access_token" not in long:
            raise _graph_error(long, "token exchange")
        return TokenSet(access_token=long["access_token"], expires_in=long.get("expires_in") or 60 * 24 * 3600, scopes=list(SCOPES))

    def identities(self, http, app, tokens):
        auth = {"access_token": tokens.access_token}
        me = json_or_error(http.get(f"{GRAPH}/me", params={**auth, "fields": "id,name,picture{url}"}), "Facebook")
        if "id" not in me:
            raise _graph_error(me, "profile lookup")
        accounts: list[AccountIdentity] = []
        url: str | None = f"{GRAPH}/me/accounts"
        params = {**auth, "fields": "id,name,access_token,picture{url},instagram_business_account{id,username,name,profile_picture_url}", "limit": 100}
        while url:
            page_data = json_or_error(http.get(url, params=params), "Facebook")
            if "error" in page_data:
                raise _graph_error(page_data, "page lookup")
            for p in page_data.get("data", []):
                accounts.append(AccountIdentity("facebook", p["id"], p.get("name", p["id"]), "", (p.get("picture", {}).get("data") or {}).get("url"),
                                                secret={"page_access_token": p.get("access_token")}))
                ig = p.get("instagram_business_account")
                if ig:
                    accounts.append(AccountIdentity("instagram", ig["id"], ig.get("name") or ig.get("username") or ig["id"], ig.get("username", ""),
                                                    ig.get("profile_picture_url"), secret={"via_page_id": p["id"], "page_access_token": p.get("access_token")}))
            url = (page_data.get("paging") or {}).get("next")
            params = {}
        if not accounts:
            raise PlatformError("No Facebook Pages were shared during login. Connect again and tick the Pages (and Instagram accounts) you want to use.", code="no_pages")
        pic = (me.get("picture", {}).get("data") or {}).get("url")
        return ConnectedIdentity(me["id"], me.get("name", "Facebook user"), pic, accounts)

    def validate_app(self, http, app, redirect_uri):
        r = http.get(f"{GRAPH}/oauth/access_token", params={"client_id": app.client_id, "client_secret": app.client_secret, "grant_type": "client_credentials"})
        data = json_or_error(r, "Facebook")
        if "access_token" not in data:
            raise PlatformError("Meta rejected this App ID / App secret.", code="invalid_client")

    def revoke(self, http, app, access_token):
        http.delete(f"{GRAPH}/me/permissions", params={"access_token": access_token})

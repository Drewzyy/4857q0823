"""End-to-end connection flows against mocked platform endpoints (no real network)."""
import hashlib
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
import respx

from clippr.models import Connection
from clippr.platforms import meta, tiktok, youtube


def form(request):
    return {k: v[0] for k, v in parse_qs(request.content.decode()).items()}


def google_token(request):
    f = form(request)
    if f.get("client_id") != "good-id":
        return httpx.Response(401, json={"error": "invalid_client"})
    if f["grant_type"] == "refresh_token":
        if f["refresh_token"] == "dead":
            return httpx.Response(400, json={"error": "invalid_grant"})
        return httpx.Response(200, json={"access_token": "yt-access-2", "expires_in": 3600, "scope": " ".join(youtube.SCOPES)})
    if f["code"] == "ai-clipper-credential-check":
        return httpx.Response(400, json={"error": "invalid_grant"})
    assert f["code_verifier"], "PKCE verifier must be sent"
    return httpx.Response(200, json={"access_token": "yt-access", "refresh_token": "yt-refresh", "expires_in": 3600, "scope": " ".join(youtube.SCOPES)})


def start(client, platform, **kw):
    r = client.post("/api/connections/start", json={"platform": platform, **kw})
    assert r.status_code == 200, r.text
    body = r.json()
    q = {k: v[0] for k, v in parse_qs(urlparse(body["authorize_url"]).query).items()}
    return body, q


@respx.mock
def test_youtube_setup_and_connect(client, ctx):
    respx.post(youtube.TOKEN_URL).mock(side_effect=google_token)
    respx.get(youtube.CHANNELS_URL).mock(return_value=httpx.Response(200, json={"items": [
        {"id": "UCabc", "snippet": {"title": "Streamer A Shorts", "customUrl": "@streamera", "thumbnails": {"default": {"url": "https://yt3/x.jpg"}}}}]}))

    # not set up yet -> clear message, no login attempted
    r = client.post("/api/connections/start", json={"platform": "youtube"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "setup_required"

    bad = client.put("/api/platforms/youtube/app", json={"client_id": "bad", "client_secret": "x"})
    assert bad.status_code == 422 and bad.json()["error"]["code"] == "invalid_client"

    good = client.post("/api/platforms/youtube/client-file", files={"file": ("client.json",
        '{"installed": {"client_id": "good-id", "client_secret": "good-secret"}}', "application/json")})
    assert good.status_code == 200, good.text
    assert good.json()["configured"] is True and "good-secret" not in good.text

    body, q = start(client, "youtube")
    assert q["client_id"] == "good-id" and q["code_challenge_method"] == "S256" and q["access_type"] == "offline"
    assert q["redirect_uri"] == "http://127.0.0.1:8765/oauth/callback/youtube"
    state = q["state"]
    assert state.startswith("8765.")

    page = client.get("/oauth/callback/youtube", params={"code": "auth-code", "state": state})
    assert page.status_code == 200 and "Connected" in page.text
    assert client.get(f"/api/connections/attempts/{state}").json()["status"] == "succeeded"

    dests = client.get("/api/destinations").json()
    assert len(dests) == 1 and dests[0]["display_name"] == "Streamer A Shorts" and dests[0]["status"] == "connected"
    conns = client.get("/api/connections").json()
    assert conns[0]["platform"] == "youtube" and "access_token" not in str(conns)
    assert ctx.secrets.get("oauth:youtube:UCabc")["refresh_token"] == "yt-refresh"

    # state is single use
    replay = client.get("/oauth/callback/youtube", params={"code": "auth-code", "state": state})
    assert "Couldn" in replay.text

    # refresh path
    with ctx.db.session() as s:
        s.query(Connection).one().access_expires_at = datetime.now(timezone.utc) - timedelta(minutes=1)
    assert ctx.connections.refresh_due() == {"connected": 1}
    assert ctx.secrets.get("oauth:youtube:UCabc")["access_token"] == "yt-access-2"
    assert ctx.secrets.get("oauth:youtube:UCabc")["refresh_token"] == "yt-refresh"  # kept

    # expired refresh token -> needs re-login, surfaced to the UI
    ctx.secrets.set("oauth:youtube:UCabc", {"access_token": "x", "refresh_token": "dead"})
    cid = conns[0]["id"]
    assert client.post(f"/api/connections/{cid}/refresh").json()["status"] == "expired"
    assert client.get("/api/destinations").json()[0]["status"] == "expired"

    # disconnect revokes, wipes secrets, keeps the destination's settings
    revoke = respx.post(youtube.REVOKE_URL).mock(return_value=httpx.Response(200))
    assert client.delete(f"/api/connections/{cid}").status_code == 204
    assert revoke.called and ctx.secrets.get("oauth:youtube:UCabc") is None
    assert client.get("/api/destinations").json()[0]["status"] == "disconnected"


@respx.mock
def test_tiktok_source_connect_with_hex_pkce(client, ctx):
    def tt_token(request):
        f = form(request)
        if f["grant_type"] == "client_credentials":
            return httpx.Response(200, json={"access_token": "app", "expires_in": 7200})
        return httpx.Response(200, json={"access_token": "tt-a", "refresh_token": "tt-r", "expires_in": 86400,
                                         "refresh_expires_in": 31536000, "open_id": "oid-1", "scope": ",".join(tiktok.SCOPES["source"])})
    respx.post(tiktok.TOKEN_URL).mock(side_effect=tt_token)
    respx.get(tiktok.USER_URL).mock(return_value=httpx.Response(200, json={
        "data": {"user": {"open_id": "oid-1", "display_name": "My Clips", "username": "my.clips", "avatar_url": "https://p/a.jpg"}},
        "error": {"code": "ok"}}))
    assert client.put("/api/platforms/tiktok/app", json={"client_id": "ck", "client_secret": "cs"}).status_code == 200
    status = client.get("/api/platforms").json()
    tt = next(p for p in status if p["key"] == "tiktok")
    assert tt["redirect_uri"] == "http://127.0.0.1:*/oauth/callback/tiktok/"

    _, q = start(client, "tiktok", purpose="source")
    assert q["redirect_uri"].endswith("/oauth/callback/tiktok/")
    assert "video.publish" not in q["scope"] and "video.list" in q["scope"]
    assert len(q["code_challenge"]) == 64 and all(c in "0123456789abcdef" for c in q["code_challenge"])

    page = client.get("/oauth/callback/tiktok/", params={"code": "c", "state": q["state"]})
    assert "Connected" in page.text
    sent = form(respx.calls.last.request) if False else None  # noqa
    srcs = client.get("/api/sources").json()
    assert srcs[0]["username"] == "my.clips" and srcs[0]["authorized"] is True
    # the verifier sent at exchange matches the challenge sent at authorize
    exch = [c for c in respx.calls if c.request.url == tiktok.TOKEN_URL and form(c.request)["grant_type"] == "authorization_code"][0]
    assert hashlib.sha256(form(exch.request)["code_verifier"].encode()).hexdigest() == q["code_challenge"]


@respx.mock
def test_meta_connect_pages_and_instagram_and_link_draft(client, ctx):
    def fb_token(request):
        p = dict(request.url.params)
        if p.get("grant_type") == "client_credentials":
            return httpx.Response(200, json={"access_token": "app|tok"})
        if p.get("grant_type") == "fb_exchange_token":
            return httpx.Response(200, json={"access_token": "long-lived", "expires_in": 5184000})
        return httpx.Response(200, json={"access_token": "short"})
    respx.get(f"{meta.GRAPH}/oauth/access_token").mock(side_effect=fb_token)
    respx.get(f"{meta.GRAPH}/me").mock(return_value=httpx.Response(200, json={"id": "fbu1", "name": "Andrew"}))
    respx.get(f"{meta.GRAPH}/me/accounts").mock(return_value=httpx.Response(200, json={"data": [
        {"id": "pg1", "name": "Gaming Highlights", "access_token": "page-token",
         "instagram_business_account": {"id": "ig1", "username": "gaming.hl", "name": "Gaming HL"}}]}))
    assert client.put("/api/platforms/meta/app", json={"client_id": "app", "client_secret": "sec"}).status_code == 200

    draft = client.post("/api/destinations", json={"platform": "instagram", "display_name": "Planned IG"}).json()
    client.patch(f"/api/destinations/{draft['id']}", json={"settings": {"hashtags": ["#keep"]}})
    _, q = start(client, "meta", link_destination_id=draft["id"])
    assert "code_challenge" not in q and "instagram_content_publish" in q["scope"]
    assert "Connected" in client.get("/oauth/callback/meta", params={"code": "c", "state": q["state"]}).text

    dests = {d["platform"]: d for d in client.get("/api/destinations").json()}
    assert set(dests) == {"facebook", "instagram"}
    assert dests["instagram"]["id"] == draft["id"]  # draft was filled in, settings kept
    assert dests["instagram"]["settings"]["hashtags"] == ["#keep"] and dests["instagram"]["handle"] == "gaming.hl"
    assert ctx.secrets.get("account:facebook:pg1")["page_access_token"] == "page-token"
    with ctx.db.session() as s:
        assert s.query(Connection).one().access_expires_at > datetime.now(timezone.utc) + timedelta(days=50)


@respx.mock
def test_user_cancel_and_bad_state(client, ctx):
    respx.post(tiktok.TOKEN_URL).mock(return_value=httpx.Response(200, json={"access_token": "app"}))
    client.put("/api/platforms/tiktok/app", json={"client_id": "ck", "client_secret": "cs"})
    _, q = start(client, "tiktok")
    page = client.get("/oauth/callback/tiktok/", params={"error": "access_denied", "state": q["state"]})
    assert "cancelled" in page.text
    assert client.get(f"/api/connections/attempts/{q['state']}").json()["status"] == "failed"
    forged = client.get("/oauth/callback/tiktok/", params={"code": "x", "state": "8765.forged"})
    assert "invalid or has expired" in forged.text
    # platform mismatch: a TikTok state can't complete a Meta callback
    _, q2 = start(client, "tiktok")
    assert "invalid" in client.get("/oauth/callback/meta", params={"code": "x", "state": q2["state"]}).text
    # messages are HTML-escaped
    _, q3 = start(client, "tiktok")
    page = client.get("/oauth/callback/tiktok/", params={"error": "server_error", "error_description": "<script>x</script>", "state": q3["state"]})
    assert "<script>x</script>" not in page.text


@respx.mock
def test_network_failure_is_friendly(client):
    respx.post(youtube.TOKEN_URL).mock(side_effect=httpx.ConnectError("down"))
    r = client.put("/api/platforms/youtube/app", json={"client_id": "a", "client_secret": "b"})
    assert r.status_code == 502 and "internet" in r.json()["error"]["message"]

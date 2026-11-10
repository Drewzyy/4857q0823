import httpx
import respx

from clippr import events
from clippr.fetch import RemotePost
from fakes import drain

HOOK = "https://discord.com/api/webhooks/123456789/abcdefghijklmnopqrstuvwxyz_123"
OWN = "https://discord.com/api/webhooks/987654321/zyxwvutsrqponmlkjihgfedcba_987"


def _setup(c):
    cid = c.post("/api/creators", json={"name": "Streamer A", "clip_permission": True, "vod_channels": ["https://www.twitch.tv/streamera"]}).json()["id"]
    sid = c.post("/api/sources", json={"input": "@a.clips", "creator_id": cid}).json()["id"]
    c.post("/api/destinations", json={"platform": "tiktok", "display_name": "A page", "creator_id": cid})
    c.post("/api/funnel/auto-route", json={})
    return sid


def test_agents_show_real_work_and_what_needs_you(env):
    ctx, c, fake = env
    sid = _setup(c)
    idle = c.get("/api/intelligence").json()
    assert {a["key"]: a["state"] for a in idle["agents"]}["production"] == "idle" and idle["needs_you"] == []
    fake.posts = []
    ctx.pipeline.check_source(sid)
    fake.posts = [RemotePost("i1", "https://www.tiktok.com/@a.clips/video/i1", "agent test")]
    ctx.pipeline.check_source(sid)
    waiting = {a["key"]: a for a in c.get("/api/intelligence").json()["agents"]}
    assert waiting["production"]["state"] == "waiting" and waiting["production"]["queued"] == 1
    drain(ctx)
    after = c.get("/api/intelligence").json()
    prod = {a["key"]: a for a in after["agents"]}["production"]
    assert prod["state"] == "idle" and prod["done_24h"] == 1
    assert any(j["agent"] == "production" and "agent test" in j["detail"] for j in after["recent"])
    assert after["needs_you"][0] == {"kind": "upload", "count": 1, "title": "1 video ready to upload", "link": "/ready"}


@respx.mock
def test_notification_service_channels_dedupe_quiet_hours_and_history(env):
    ctx, c, fake = env
    default = respx.post(HOOK).mock(return_value=httpx.Response(204))
    own = respx.post(OWN).mock(return_value=httpx.Response(204))
    assert c.put("/api/notifications", json={"webhook_url": HOOK, "category_webhooks": {"approvals": OWN}}).status_code == 200
    st = c.get("/api/notifications").json()
    cats = {x["key"]: x for x in st["categories"]}
    assert st["configured"] and cats["approvals"]["own_webhook_hint"] == "…ba_987" and cats["production"]["own_webhook_hint"] is None
    assert HOOK not in str(st) and OWN not in str(st)  # webhook URLs never come back to the app

    # Clip ready goes to the approvals channel, new posts to the default one; the same event is only sent once.
    assert events.emit(ctx, "approvals", "Clip ready", dedupe_key="ready:1") is not None
    assert events.emit(ctx, "approvals", "Clip ready", dedupe_key="ready:1") is None
    events.emit(ctx, "production", "New post")
    drain(ctx)
    assert own.call_count == 1 and default.call_count == 1

    # A turned-off category is recorded but not sent; so is anything below the minimum priority.
    c.put("/api/notifications", json={"categories": {"production": False}, "min_priority": "normal"})
    events.emit(ctx, "production", "Muted")
    events.emit(ctx, "approvals", "Too minor", priority="low")
    drain(ctx)
    assert default.call_count == 1 and own.call_count == 1
    history = c.get("/api/events").json()
    assert [(e["title"], e["delivery"]) for e in history[:2]] == [("Too minor", "off"), ("Muted", "off")]
    assert {e["title"]: e["delivery"] for e in history}["Clip ready"] == "sent"

    # Quiet hours hold everything but urgent events.
    assert c.put("/api/notifications", json={"quiet_start": "00:00", "quiet_end": "23:59"}).status_code == 200
    events.emit(ctx, "approvals", "Held until morning")
    events.emit(ctx, "approvals", "Urgent", priority="urgent")
    drain(ctx)
    deliveries = {e["title"]: e["delivery"] for e in c.get("/api/events").json()}
    assert deliveries["Held until morning"] == "held" and deliveries["Urgent"] == "sent"
    assert c.put("/api/notifications", json={"quiet_start": "22:00", "quiet_end": ""}).status_code == 422
    assert c.put("/api/notifications", json={"categories": {"bogus": True}}).status_code == 422


@respx.mock
def test_discord_down_never_blocks_clips(env):
    ctx, c, fake = env
    respx.post(HOOK).mock(return_value=httpx.Response(500))
    c.put("/api/notifications", json={"webhook_url": HOOK})
    sid = _setup(c)
    fake.posts = []
    ctx.pipeline.check_source(sid)
    fake.posts = [RemotePost("d1", "https://www.tiktok.com/@a.clips/video/d1", "discord down")]
    ctx.pipeline.check_source(sid)
    drain(ctx)
    assert c.get("/api/references").json()[0]["status"] == "ready"
    assert any(e["delivery"] == "failed" for e in c.get("/api/events").json())

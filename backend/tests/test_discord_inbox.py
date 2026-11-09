import httpx
import respx

from clippr.discord_inbox import API, NO_CONTENT, parse
from clippr.fetch import RemotePost
from fakes import drain

TOKEN = "x" * 40
CH = "111111111111111111"
CORE = [(1, "The Core", ["https://www.twitch.tv/jasontheween", "https://kick.com/lacy"]), (2, "Kai", ["https://www.twitch.tv/kaicenat"])]


def test_parse_links_and_streamer_names():
    assert parse("https://www.tiktok.com/@clips/video/123 jason", CORE) == [("https://www.tiktok.com/@clips/video/123", None)]  # "jason" alone is too vague
    assert parse("<https://www.tiktok.com/@clips/video/123> jasontheween", CORE) == [("https://www.tiktok.com/@clips/video/123", 1)]
    assert parse("kaicenat https://vm.tiktok.com/ZMabc/", CORE) == [("https://vm.tiktok.com/ZMabc/", 2)]
    # What TikTok's Share > Copy link gives on a phone, with its tracking query.
    assert parse("https://www.tiktok.com/t/ZT8abc123/?_t=ZT-8x&_r=1 jasontheween", CORE) == [("https://www.tiktok.com/t/ZT8abc123/?_t=ZT-8x&_r=1", 1)]
    assert parse("lol look at this https://www.tiktok.com/@clips", CORE) == []  # a profile, not a video


def _discord(messages):
    respx.get(f"{API}/users/@me").mock(return_value=httpx.Response(200, json={"username": "VyralBot"}))
    respx.get(f"{API}/users/@me/guilds").mock(return_value=httpx.Response(200, json=[{"id": "9", "name": "My server"}]))
    respx.get(f"{API}/guilds/9/channels").mock(return_value=httpx.Response(200, json=[
        {"id": CH, "name": "vyral-inbox", "type": 0}, {"id": "222", "name": "Voice", "type": 2}]))
    respx.get(url__regex=rf"{API}/channels/{CH}/messages\?limit=1").mock(return_value=httpx.Response(200, json=[{"id": "100"}]))
    respx.get(url__regex=rf"{API}/channels/{CH}/messages\?after=").mock(side_effect=lambda req: httpx.Response(200, json=messages()))
    return respx.put(url__regex=rf"{API}/channels/{CH}/messages/\d+/reactions/.*").mock(return_value=httpx.Response(204))


@respx.mock
def test_links_posted_in_discord_become_clips(env):
    ctx, c, fake = env
    a = c.post("/api/creators", json={"name": "Streamer A", "clip_permission": True, "vod_channels": ["https://www.twitch.tv/streamera"]}).json()["id"]
    c.post("/api/destinations", json={"platform": "tiktok", "display_name": "A page", "creator_id": a})
    inbox = []
    reactions = _discord(lambda: inbox)

    assert c.put("/api/discord-inbox", json={"token": "bad"}).status_code == 422  # too short to be a token
    v = c.put("/api/discord-inbox", json={"token": TOKEN}).json()
    assert v["configured"] and v["bot"] == "VyralBot"
    assert [ch["name"] for ch in c.get("/api/discord-inbox/channels").json()] == ["vyral-inbox"]  # text channels only
    v = c.put("/api/discord-inbox", json={"channel_id": CH}).json()
    assert v["channel_name"] == "vyral-inbox" and v["server"] == "My server"
    assert TOKEN not in str(v)

    assert ctx.inbox.poll() == {"started": True}  # older messages aren't requests
    fake.post_details = lambda url: RemotePost(url.rsplit("/", 1)[-1], url, "insane moment")
    inbox[:] = [
        {"id": "102", "author": {"id": "u"}, "content": "https://www.tiktok.com/@clipper/video/555 streamera"},
        {"id": "101", "author": {"id": "u"}, "content": "good morning"},
        {"id": "103", "author": {"id": "w", "bot": True}, "webhook_id": "w", "content": "Clip ready https://www.tiktok.com/@x/video/9"},
    ]
    assert ctx.inbox.poll() == {"queued": 1}
    drain(ctx)
    ref = c.get("/api/references").json()[0]
    assert ref["status"] == "ready" and ref["creator"]["name"] == "Streamer A"
    reacted = [str(call.request.url) for call in reactions.calls]
    assert len(reacted) == 2 and any("/102/" in u for u in reacted) and not any("/103/" in u for u in reacted)

    # Without Message Content Intent, Discord sends empty text: say how to fix it.
    inbox[:] = [{"id": "104", "author": {"id": "u"}, "content": ""}]
    ctx.inbox.poll()
    assert c.get("/api/discord-inbox").json()["last_error"] == NO_CONTENT
    assert c.delete("/api/discord-inbox").status_code == 204
    assert c.get("/api/discord-inbox").json()["configured"] is False

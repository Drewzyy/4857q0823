"""Campaigns: reading a pasted post, which clips and videos count, the API, and the Discord message."""
import json
from datetime import date, datetime, timedelta, timezone

import httpx
import respx

from clippr import campaigns, describe, mcp
from clippr.fetch import RemotePost
from clippr.models import Campaign, Clip, ClipOutput
from fakes import drain
from test_pipeline import HOOK, setup_accounts

POST = """💰 LACY GTA VI Marathon Pool Campaign
Clip and create content from approved footage to earn money based on your views!
📌 Campaign Information
* Creator: Lacy
* Content Type: Social media clipping
* Eligible Platforms: Tiktok, Instagram, YouTube, X
🎬 Approved Footage
Content must be sourced from any stream, video or clip featuring Lacy during his GTA marathon, beginning November 18th, 2026.
$12,500 LACY GTA VI Marathon Pool Campaign
Min Views (MVR)
750,000
Audience
English Speaking
[Join Campaign](https://contentrewards.com/c/campaigns/a5c63fad-cd53-4b81-9305-4a2d1696872a?src=share)[Join Discord](https://discord.com/invite/reachclipping)
[Requirements](https://reachclipping.com/LACYGTA#requirements)
* Your caption/text overlay must mention LACY's name
* Your captions must use the hashtag: #LACY
3. Submit Your Video Links
Once verified, head back to Content Rewards and paste the link to every LACY clip you've posted. Submit within 30 minutes of posting."""

NOW = datetime(2026, 11, 20, 12, 0, tzinfo=timezone.utc)


def test_parse_the_example_post():
    p = campaigns.parse(POST)
    assert p["name"] == "LACY GTA VI Marathon Pool Campaign"
    assert p["pool"] == "$12,500" and p["creator"] == "Lacy" and p["audience"] == "English Speaking"
    assert p["platforms"] == ["tiktok", "instagram", "youtube", "x"]
    assert p["min_views"] == 750000 and p["required_hashtags"] == ["#LACY"] and p["must_mention"] == ["LACY"]
    assert p["footage_from"] == date(2026, 11, 18) and p["submit_within_minutes"] == 30
    assert p["join_url"].startswith("https://contentrewards.com/c/campaigns/a5c63fad") and p["discord_url"] == "https://discord.com/invite/reachclipping"
    assert p["guidelines_url"] == "https://reachclipping.com/LACYGTA#requirements" and p["rules"] == POST


def test_parse_leaves_missing_things_empty():
    p = campaigns.parse("Some Campaign\nCreator\nBob\nMin views: 2M")
    assert p["creator"] == "Bob" and p["min_views"] == 2_000_000 and p["platforms"] == [] and p["footage_from"] is None and p["pool"] == ""


def camp(**kw) -> Campaign:
    base = dict(id=1, name="Lacy GTA", tag="lacy-gta", creator_id=1, status="live", min_views=0, platforms=["tiktok", "youtube"], footage_from=date(2026, 11, 18),
                ends_at=None, required_hashtags=["#LACY"], must_mention=["LACY"], keywords=[], destination_ids=[])
    return Campaign(**{**base, **kw})


def clip(**kw) -> Clip:
    base = dict(id=1, creator_id=1, title="Big moment", created_at=NOW, stream_date=None, words=[], safety=None)
    return Clip(**{**base, **kw})


def test_matches_creator_dates_and_keywords():
    assert campaigns.matches(camp(), clip())
    assert not campaigns.matches(camp(), clip(creator_id=2))
    assert not campaigns.matches(camp(creator_id=None), clip(creator_id=None))
    assert not campaigns.matches(camp(), clip(stream_date=datetime(2026, 11, 17, 23, tzinfo=timezone.utc)))  # footage from before it began
    assert campaigns.matches(camp(), clip(stream_date=datetime(2026, 11, 18, 1, tzinfo=timezone.utc)))
    assert not campaigns.matches(camp(ends_at=date(2026, 11, 20)), clip())  # created on the end date: too late
    gta = camp(keywords=["GTA"])
    assert not campaigns.matches(gta, clip())
    assert campaigns.matches(gta, clip(title="Lacy plays gta"))
    assert campaigns.matches(gta, clip(words=[{"start": 0, "end": 1, "text": "Gta"}]))
    assert campaigns.matches(gta, clip(safety={"game": "Grand Theft Auto V - GTA"}))


def out(**kw) -> ClipOutput:
    base = dict(id=1, clip_id=1, destination_id=5, platform="tiktok", title="Big moment", description="so good #LACY", status="uploaded", post_url=None)
    return ClipOutput(**{**base, **kw})


def test_qualifies_rules():
    c = camp()
    assert campaigns.qualifies(c, out()) == (True, [])  # the hashtag itself says the name
    assert campaigns.qualifies(c, out(description="LACY did it #lacy"))[0]
    assert campaigns.qualifies(c, out(status="ready", post_url="https://www.tiktok.com/@a/video/1"))[0]
    assert campaigns.qualifies(c, out(status="ready"))[1] == ["Not posted yet"]
    assert campaigns.qualifies(c, out(platform="instagram"))[1] == ["Instagram isn't an eligible platform"]
    assert campaigns.qualifies(c, out(description="LACY did it #lacyfan"))[1] == ["Caption is missing #LACY"]  # a longer hashtag isn't the hashtag
    assert campaigns.qualifies(c, out(description="#LACY"))[0]
    assert campaigns.qualifies(camp(required_hashtags=[]), out(description="so good", title="nothing"))[1] == ["Caption doesn't mention LACY"]
    assert campaigns.qualifies(c, out(description="hello"))[1] == ["Caption is missing #LACY", "Caption doesn't mention LACY"]
    assert campaigns.qualifies(camp(destination_ids=[9]), out())[1] == ["Posted from a page that isn't on this campaign"]
    assert campaigns.qualifies(camp(destination_ids=[5]), out())[0]
    assert campaigns.qualifies(camp(platforms=[]), out(platform="facebook"))[0]  # no list: any platform


def make_clip(ctx, creator_id, title="Big moment", stream_date=None, description="great clip") -> tuple[int, int]:
    with ctx.db.session() as s:
        c = Clip(creator_id=creator_id, title=title, stream_date=stream_date, expires_at=datetime.now(timezone.utc) + timedelta(days=30))
        s.add(c)
        s.flush()
        o = ClipOutput(clip_id=c.id, platform="tiktok", title=title, description=description)
        s.add(o)
        s.flush()
        return c.id, o.id


def body(creator_id, **kw) -> dict:
    return {"name": "Lacy GTA", "tag": "lacy-gta", "creator_id": creator_id, "footage_from": "2026-11-18", "required_hashtags": ["LACY"],
            "must_mention": ["LACY"], "platforms": ["tiktok"], "min_views": 1000, "join_url": "https://contentrewards.com/c/1", "submit_within_minutes": 30, **kw}


def test_add_search_edit_and_delete(ctx, client):
    lacy = client.post("/api/creators", json={"name": "Lacy"}).json()["id"]
    assert client.post("/api/campaigns", json=body(lacy, tag="Bad Tag")).status_code == 422
    assert client.post("/api/campaigns", json=body(lacy, name="")).status_code == 422
    assert client.post("/api/campaigns", json=body(lacy, join_url="javascript:alert(1)")).status_code == 422
    assert client.post("/api/campaigns", json=body(999)).status_code == 422
    assert client.post("/api/campaigns", json=body(lacy, destination_ids=[999])).status_code == 422
    made = client.post("/api/campaigns", json=body(lacy))
    assert made.status_code == 201, made.text
    c = made.json()
    assert c["required_hashtags"] == ["#LACY"] and c["creator"]["name"] == "Lacy" and c["views"] == 0 and c["status"] == "live"
    assert client.post("/api/campaigns", json=body(lacy)).status_code == 409  # the tag is taken

    assert [x["id"] for x in client.get("/api/campaigns", params={"q": "GTA"}).json()] == [c["id"]]  # by tag, any case
    assert [x["id"] for x in client.get("/api/campaigns", params={"q": "lacy g"}).json()] == [c["id"]]  # by name
    assert client.get("/api/campaigns", params={"q": "nope"}).json() == [] and client.get("/api/campaigns", params={"q": "%"}).json() == []
    assert len(client.get("/api/campaigns").json()) == 1

    r = client.patch(f"/api/campaigns/{c['id']}", json={"status": "ended", "ends_at": None})
    assert r.json()["status"] == "ended" and r.json()["tag"] == "lacy-gta" and r.json()["min_views"] == 1000  # only what was sent changes
    assert client.patch(f"/api/campaigns/{c['id']}", json={"tag": "x"}).status_code == 422
    assert client.patch("/api/campaigns/999", json={"status": "live"}).status_code == 404

    cid, _ = make_clip(ctx, lacy)
    client.post(f"/api/campaigns/{c['id']}/clips", json={"clip_id": cid})
    assert client.delete(f"/api/campaigns/{c['id']}").status_code == 204
    assert client.get("/api/campaigns").json() == []
    with ctx.db.session() as s:
        assert s.get(Clip, cid)  # the clip stays


def test_parse_endpoint_finds_the_streamer(client):
    lacy = client.post("/api/creators", json={"name": "Lacy"}).json()["id"]
    r = client.post("/api/campaigns/parse", json={"text": POST}).json()
    assert r["creator_id"] == lacy and r["footage_from"] == "2026-11-18" and r["min_views"] == 750000
    assert client.post("/api/campaigns/parse", json={"text": ""}).status_code == 422


def test_link_unlink_suggested_and_qualifying(ctx, client):
    lacy = client.post("/api/creators", json={"name": "Lacy"}).json()["id"]
    other = client.post("/api/creators", json={"name": "Other"}).json()["id"]
    cid = client.post("/api/campaigns", json=body(lacy)).json()["id"]
    fits, out_id = make_clip(ctx, lacy, "Lacy GTA moment")
    make_clip(ctx, other)
    make_clip(ctx, lacy, stream_date=datetime(2026, 11, 1, tzinfo=timezone.utc))  # footage from before the campaign
    got = client.get(f"/api/campaigns/{cid}/clips").json()
    assert got["clips"] == [] and [x["clip_id"] for x in got["suggested"]] == [fits]

    assert client.post(f"/api/campaigns/{cid}/clips", json={"clip_id": 999}).status_code == 404
    assert client.post(f"/api/campaigns/{cid}/clips", json={"clip_id": fits}).status_code == 201
    assert client.post(f"/api/campaigns/{cid}/clips", json={"clip_id": fits}).status_code == 201  # twice is the same as once
    got = client.get(f"/api/campaigns/{cid}/clips").json()
    assert got["suggested"] == [] and len(got["clips"]) == 1
    page = got["clips"][0]["outputs"][0]
    assert got["clips"][0]["added_by"] == "you" and page["reasons"] == ["Not posted yet"] and not page["qualifies"]
    with ctx.db.session() as s:
        assert s.get(ClipOutput, out_id).description == "great clip\n\n#LACY"  # the campaign's hashtag was added

    assert client.put(f"/api/outputs/{out_id}/post", json={"post_url": "https://www.tiktok.com/@a/video/1"}).status_code == 200
    client.post(f"/api/outputs/{out_id}/metrics", json={"views": 400})
    page = client.get(f"/api/campaigns/{cid}/clips").json()["clips"][0]["outputs"][0]
    assert page["qualifies"] and page["views"] == 400 and page["post_url"].endswith("/video/1")
    assert client.get("/api/campaigns").json()[0]["views"] == 400

    assert client.delete(f"/api/campaigns/{cid}/clips/{fits}").status_code == 204
    assert client.delete(f"/api/campaigns/{cid}/clips/{fits}").status_code == 404
    assert client.get(f"/api/campaigns/{cid}/clips").json()["clips"] == []


def test_muse_can_list_campaigns(ctx, client):
    lacy = client.post("/api/creators", json={"name": "Lacy"}).json()["id"]
    cid = client.post("/api/campaigns", json=body(lacy)).json()["id"]
    clip_id, _ = make_clip(ctx, lacy)
    client.post(f"/api/campaigns/{cid}/clips", json={"clip_id": clip_id})
    [row] = mcp.list_campaigns(ctx, {})
    assert row["tag"] == "lacy-gta" and row["creator"] == "Lacy" and row["live"] and row["tagged_clip_ids"] == [clip_id]
    assert row["required_hashtags"] == ["#LACY"] and "list_campaigns" in mcp.TOOLS


@respx.mock
def test_clip_made_by_the_pipeline_is_tagged_and_you_hear_when_it_qualifies(env):
    ctx, c, fake = env
    discord = respx.post(HOOK).mock(return_value=httpx.Response(204))
    c.put("/api/notifications", json={"webhook_url": HOOK})
    cid, sid, *_ = setup_accounts(c)
    camp_id = c.post("/api/campaigns", json=body(cid, tag="streamera", name="Streamer A Pool", footage_from="2020-01-01", must_mention=[], min_views=1000)).json()["id"]
    later = c.post("/api/campaigns", json=body(cid, tag="late", name="Too late", footage_from="2020-01-01", ends_at="2021-01-01", must_mention=[])).json()["id"]

    fake.posts = [RemotePost("old1", "https://www.tiktok.com/@a.clips/video/old1", "old one")]
    ctx.pipeline.check_source(sid)
    fake.posts = [RemotePost("new1", "https://www.tiktok.com/@a.clips/video/new1", "He actually did it"), *fake.posts]
    ctx.pipeline.check_source(sid)
    drain(ctx)

    [clip] = c.get("/api/clips").json()
    assert all(o["description"].endswith("#LACY") for o in clip["outputs"]), clip["outputs"]  # the campaign's hashtag is on every page's caption
    tagged = c.get(f"/api/campaigns/{camp_id}/clips").json()["clips"]
    assert [t["clip_id"] for t in tagged] == [clip["id"]] and tagged[0]["added_by"] == "auto"
    assert c.get(f"/api/campaigns/{later}/clips").json()["clips"] == []  # its dates were over

    tiktok = next(o for o in clip["outputs"] if o["platform"] == "tiktok")
    sent = discord.call_count
    assert c.put(f"/api/outputs/{tiktok['id']}/post", json={"post_url": "https://www.tiktok.com/@a/video/9"}).status_code == 200
    drain(ctx)
    assert discord.call_count == sent + 1
    message = json.loads(discord.calls.last.request.content)["embeds"][0]
    assert message["title"].endswith("qualifies for Streamer A Pool") and "Submit it within 30 minutes: https://contentrewards.com/c/1" in message["description"]
    assert "https://www.tiktok.com/@a/video/9" in message["description"]

    ctx.jobs.enqueue("campaigns.check", {})
    drain(ctx)
    assert discord.call_count == sent + 1  # never twice for the same video

    c.post(f"/api/outputs/{tiktok['id']}/metrics", json={"views": 1500})
    ctx.jobs.enqueue("campaigns.check", {})
    ctx.jobs.enqueue("campaigns.check", {})
    drain(ctx)
    assert discord.call_count == sent + 2 and "passed 1,000 views" in json.loads(discord.calls.last.request.content)["embeds"][0]["title"]


def test_apply_rules_adds_only_what_is_missing():
    rules = {"hashtags": ["#LACY"], "mention": ["Lacy"], "extra": "Follow for more"}
    full = "Lacy did it\n\nFollow for more\n\n#lacy #gaming"
    assert describe.apply_rules(full, rules) == full  # nothing missing, nothing changed (any case)
    assert describe.apply_rules("Big moment\n\n#gaming #vyralclips", {"hashtags": ["#LACY"]}) == "Big moment\n\n#gaming #vyralclips #LACY"
    assert describe.apply_rules("Big moment", {"hashtags": ["#LACY"]}) == "Big moment\n\n#LACY"
    assert describe.apply_rules("#vyralclips #shorts", {"hashtags": ["#LACY"]}, "youtube") == "#vyralclips #shorts #LACY"
    assert describe.apply_rules("Big moment\n\n#gaming", rules) == "Big moment\n\nFollow for more\n\nWith Lacy\n\n#gaming #LACY"
    assert describe.apply_rules("#gaming", {"mention": ["Lacy"]}, "youtube", title="Lacy wins") == "#gaming"  # the title says the name
    assert describe.apply_rules("#lacyfan", {"hashtags": ["#LACY"]}) == "#lacyfan #LACY"  # a longer hashtag isn't it
    assert describe.apply_rules("anything", None) == "anything"
    cut = describe.apply_rules("x" * 2300 + "\n\n#gaming", {"hashtags": ["#LACY"]}, "tiktok")
    assert len(cut) == 2200 and cut.endswith("#gaming #LACY")  # the text is cut, never the rule


def test_streamer_rules_are_saved_and_checked(client):
    cid = client.post("/api/creators", json={"name": "Lacy"}).json()["id"]
    assert client.get("/api/streamers").json()[0]["rules"] == {"hashtags": [], "mention": [], "extra": "", "notes": ""}
    r = client.patch(f"/api/streamers/{cid}", json={"rules": {"hashtags": ["LACY", "#gta"], "mention": ["Lacy"], "extra": "Follow", "notes": "No swearing"}})
    assert r.json()["rules"] == {"hashtags": ["#LACY", "#gta"], "mention": ["Lacy"], "extra": "Follow", "notes": "No swearing"}
    assert client.patch(f"/api/streamers/{cid}", json={"rules": {"hashtags": ["two words"]}}).status_code == 422
    assert client.patch(f"/api/streamers/{cid}", json={"rules": {"hashtags": [f"#t{i}" for i in range(11)]}}).status_code == 422
    assert client.patch(f"/api/streamers/{cid}", json={"rules": {"extra": "x" * 301}}).status_code == 422


def test_campaign_rules_are_copied_into_the_streamer_without_losing_theirs(client):
    cid = client.post("/api/creators", json={"name": "Lacy"}).json()["id"]
    client.patch(f"/api/streamers/{cid}", json={"rules": {"hashtags": ["#gta", "#lacy"], "extra": "Follow", "notes": "Mine"}})
    camp = client.post("/api/campaigns", json=body(cid, rules="Must use #LACY")).json()["id"]
    r = client.post(f"/api/campaigns/{camp}/apply-rules").json()
    assert r["hashtags"] == ["#gta", "#lacy", "#LACY"]
    assert r["mention"] == ["LACY"] and r["extra"] == "Follow" and r["notes"].startswith("Mine\n\nLacy GTA\nMust use #LACY")
    assert client.post(f"/api/campaigns/{camp}/apply-rules").json() == r  # twice changes nothing
    nobody = client.post("/api/campaigns", json=body(None, tag="nobody")).json()["id"]
    assert client.post(f"/api/campaigns/{nobody}/apply-rules").status_code == 422


@respx.mock
def test_every_new_clip_of_a_streamer_follows_their_rules(env):
    ctx, c, fake = env
    respx.post(HOOK).mock(return_value=httpx.Response(204))
    cid, sid, *_ = setup_accounts(c)
    c.patch(f"/api/streamers/{cid}", json={"rules": {"hashtags": ["#STREAMERA"], "mention": ["Streamer A"], "extra": "Clipped by Vyral"}})
    fake.posts = [RemotePost("old1", "https://www.tiktok.com/@a.clips/video/old1", "old one")]
    ctx.pipeline.check_source(sid)
    fake.posts = [RemotePost("new1", "https://www.tiktok.com/@a.clips/video/new1", "He actually did it"), *fake.posts]
    ctx.pipeline.check_source(sid)
    drain(ctx)
    [clip] = c.get("/api/clips").json()
    assert len(clip["outputs"]) == 2
    for o in clip["outputs"]:
        assert o["description"].endswith("#STREAMERA"), o["description"]
        assert "Clipped by Vyral" in o["description"] and describe.has_name(o["description"] + "\n" + o["video_title"], "Streamer A")


BULLETS = """## Summer Clip-Off Campaign
**Streamer:** Kai
**Platforms:**
- TikTok
- YouTube Shorts
Total prize pool: $5,000
Requirements:
1. Videos must be between 15 and 60 seconds long
2. English captions only
3. No logos or watermarks from other clippers
4. Kai must be the main focus of the video
5. Use the hashtags #KaiClips and #Valorant in your caption
6. Do not use #fyp
7. Text on screen must mention Kai's name
Minimum 250K views required. Submit within 2 hours of posting.
What to look for:
- VALORANT clutches
Join here: https://whop.com/kai-clips/."""

PLAIN = """LACY x Clipping
Creator: Lacy
Max 90s. Clips should be under 1 minute and at least 10 sec
Please mention the creator's name in your post
Min. 2M views
Required hashtags:
- #lacy
- #gta
Platform: X, Twitter"""


def test_parse_reads_rules_in_other_layouts():
    p = campaigns.parse(BULLETS)
    assert p["name"] == "Summer Clip-Off Campaign" and p["creator"] == "Kai" and p["pool"] == "$5,000" and p["platforms"] == ["tiktok", "youtube"]
    assert p["min_views"] == 250_000 and p["submit_within_minutes"] == 120 and p["join_url"] == "https://whop.com/kai-clips/"
    assert p["required_hashtags"] == ["#KaiClips", "#Valorant"]  # not the #fyp it says not to use
    assert p["must_mention"] == [] and p["keywords"] == ["VALORANT"]  # the name is for the video's text, not the caption
    assert p["clip_rules"] == {"min_seconds": 15, "max_seconds": 60, "overlay_mentions": ["Kai"], "language": "English", "no_logos": True, "focus_creator": True}

    p = campaigns.parse(PLAIN)
    assert p["name"] == "LACY x Clipping" and p["creator"] == "Lacy" and p["platforms"] == ["x"] and p["min_views"] == 2_000_000
    assert p["must_mention"] == ["Lacy"] and p["required_hashtags"] == ["#lacy", "#gta"]  # "the creator's name" is the streamer's
    assert p["clip_rules"] == {"min_seconds": 10, "max_seconds": 60, "overlay_mentions": [], "language": "", "no_logos": False, "focus_creator": False}

    r = campaigns.parse(POST)["clip_rules"]  # the first example: the name is wanted in the caption and on the video
    assert r["overlay_mentions"] == ["LACY"] and r["language"] == "English" and r["max_seconds"] == 0 and campaigns.parse(POST)["keywords"] == ["GTA"]
    assert campaigns.parse("Submit within 30 minutes of posting your clip")["clip_rules"]["max_seconds"] == 0  # a deadline isn't a length
    assert campaigns.parse("Videos can't be longer than 2 minutes")["clip_rules"]["max_seconds"] == 120


def test_strictest_rules_win():
    a = camp(clip_rules={"min_seconds": 10, "max_seconds": 90, "overlay_mentions": ["LACY"]})
    b = camp(clip_rules={"min_seconds": 20, "max_seconds": 60, "overlay_mentions": ["Lacy", "Dani"]})
    assert campaigns.merge_clip_rules([a, b]) == {"min_seconds": 20, "max_seconds": 60, "overlay_mentions": ["LACY", "Lacy", "Dani"]}
    assert campaigns.merge_clip_rules([]) == {"min_seconds": 0, "max_seconds": 0, "overlay_mentions": []}
    assert campaigns.merge_clip_rules([camp(clip_rules={"min_seconds": 50, "max_seconds": 30})])["min_seconds"] == 30  # never above the longest
    assert campaigns.fits(camp(keywords=["gta"]), 1, date(2026, 11, 20), "Lacy plays GTA") and not campaigns.fits(camp(), 1, date(2026, 11, 1), "")


def test_titles_and_cuts_follow_a_campaigns_length_and_names():
    import numpy as np
    from clippr import preedit, titles
    from clippr.media.overlay import Word
    words = [Word(6.0 + i * 0.4, 6.3 + i * 0.4, t) for i, t in enumerate("no way he actually did that".split())]
    quote, is_quote = titles.make_title(words, "Lacy", 6.5, ["LACY"])
    assert is_quote and quote.startswith("LACY: “no way") and "LACY" not in titles.make_title(words, "Lacy", 6.5)[0]  # named only when asked
    assert titles.make_title(words, "Lacy", 6.5, ["Dani", "Lacy"])[0].startswith("Dani and Lacy: ")
    assert titles.make_title([], "Lacy", None, ["LACY"])[0].count("Lacy") == 1 and "Dani" in titles.make_title([], "Lacy", None, ["Dani"])[0]  # a summary already names the streamer
    db = np.full(600, -30.0)
    db[300:320] = -5  # a moment at 30 s of a 60 s clip
    a, b = preedit.best_window(db, [], 60.0, max_s=15)
    assert b - a <= 15 and a < 30 < b
    a, b = preedit.best_window(db, [], 60.0, min_s=44)
    assert b - a >= 44
    assert preedit.best_window(None, [], 8.0, min_s=30) == (0.0, 8.0)  # the footage is all there is
    assert preedit.best_window(None, [], 40.0, max_s=20)[1] - preedit.best_window(None, [], 40.0, max_s=20)[0] == 20  # even with no loudness to go by


def test_rules_api_validates_and_returns_the_clip_rules(client):
    lacy = client.post("/api/creators", json={"name": "Lacy"}).json()["id"]
    assert client.post("/api/campaigns", json=body(lacy, clip_rules={"min_seconds": 60, "max_seconds": 30})).status_code == 422
    assert client.post("/api/campaigns", json=body(lacy, clip_rules={"overlay_mentions": ["x" * 61]})).status_code == 422
    assert client.post("/api/campaigns", json=body(lacy, clip_rules={"max_seconds": -1})).status_code == 422
    made = client.post("/api/campaigns", json=body(lacy, clip_rules={"max_seconds": 60, "overlay_mentions": [" LACY ", ""], "no_logos": True})).json()
    assert made["clip_rules"] == {"min_seconds": 0, "max_seconds": 60, "overlay_mentions": ["LACY"], "language": "", "no_logos": True, "focus_creator": False}
    assert client.get("/api/campaigns").json()[0]["clip_rules"]["max_seconds"] == 60
    assert client.patch(f"/api/campaigns/{made['id']}", json={"status": "ended"}).json()["clip_rules"]["max_seconds"] == 60  # kept when not sent
    assert client.patch(f"/api/campaigns/{made['id']}", json={"clip_rules": {"min_seconds": 5}}).json()["clip_rules"]["max_seconds"] == 0
    assert client.post("/api/campaigns/parse", json={"text": BULLETS}).json()["clip_rules"]["min_seconds"] == 15


def clip_seconds(e: dict) -> float:
    return e["end"] - e["start"] + (e["hook"][1] - e["hook"][0] if e.get("hook") else 0)


@respx.mock
def test_a_new_clip_is_cut_and_titled_for_its_campaign(env):
    ctx, c, fake = env
    respx.post(HOOK).mock(return_value=httpx.Response(204))
    cid, sid, *_ = setup_accounts(c)
    rules = {"max_seconds": 14, "overlay_mentions": ["STREAMER A"], "no_logos": True}
    c.post("/api/campaigns", json=body(cid, tag="streamera", name="Streamer A Pool", footage_from="2020-01-01", must_mention=[], clip_rules=rules))
    fake.posts = [RemotePost("old1", "https://www.tiktok.com/@a.clips/video/old1", "old one")]
    ctx.pipeline.check_source(sid)
    fake.posts = [RemotePost("new1", "https://www.tiktok.com/@a.clips/video/new1", "He actually did it"), *fake.posts]
    ctx.pipeline.check_source(sid)
    drain(ctx)
    [clip] = c.get("/api/clips").json()
    assert clip["title"].startswith("STREAMER A: “no way he actually did that")  # its name is on the video, the quote word for word
    with ctx.db.session() as s:
        e = s.get(Clip, clip["id"]).edit
    assert e["texts"][0]["text"] == clip["title"] and 0 < clip_seconds(e) <= 14, e  # cut to the campaign's longest (the teaser counts)


@respx.mock
def test_tagging_a_clip_that_breaks_the_rules_cuts_it_again(env):
    ctx, c, fake = env
    respx.post(HOOK).mock(return_value=httpx.Response(204))
    cid, sid, *_ = setup_accounts(c)
    fake.posts = [RemotePost("old1", "https://www.tiktok.com/@a.clips/video/old1", "old one")]
    ctx.pipeline.check_source(sid)
    fake.posts = [RemotePost("new1", "https://www.tiktok.com/@a.clips/video/new1", "He actually did it"), *fake.posts]
    ctx.pipeline.check_source(sid)
    drain(ctx)
    [clip] = c.get("/api/clips").json()
    with ctx.db.session() as s:
        before = clip_seconds(s.get(Clip, clip["id"]).edit)
    assert before > 8 and not clip["title"].startswith("STREAMER A")
    camp_id = c.post("/api/campaigns", json=body(cid, tag="late", name="Late one", footage_from="2020-01-01", must_mention=[],
                                                  clip_rules={"max_seconds": 8, "overlay_mentions": ["STREAMER A"]})).json()["id"]
    assert c.post(f"/api/campaigns/{camp_id}/clips", json={"clip_id": clip["id"]}).status_code == 201
    drain(ctx)
    [clip] = c.get("/api/clips").json()
    with ctx.db.session() as s:
        e = s.get(Clip, clip["id"]).edit
    assert clip["title"].startswith("STREAMER A: ") and 0 < clip_seconds(e) <= 8 and e["texts"][0]["text"] == clip["title"]
    assert all(o["video_title"] == clip["title"] and o["render_state"] == "ready" for o in clip["outputs"])
    assert campaigns.complies(Clip(edit=e, title=clip["title"]), {"min_seconds": 0, "max_seconds": 8, "overlay_mentions": ["STREAMER A"]})


def test_a_game_abbreviation_matches_twitchs_full_name():
    from clippr.campaigns import _searchable
    assert "gta" in _searchable("He finally got the plane in Grand Theft Auto V")
    assert "gta" not in _searchable("just chatting with chat")

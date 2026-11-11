"""Streamers as sources: a stream link, the pages their clips go to, and watching, all in one place."""
from datetime import datetime, timedelta, timezone

from clippr.fetch import RemotePost
from fakes import drain


def test_add_a_streamer_with_their_stream_and_pages(env):
    ctx, c, fake = env
    tt = c.post("/api/destinations", json={"platform": "tiktok", "display_name": "valk.clips"}).json()["id"]
    yt = c.post("/api/destinations", json={"platform": "youtube", "display_name": "valk shorts"}).json()["id"]
    other = c.post("/api/destinations", json={"platform": "tiktok", "display_name": "other page"}).json()["id"]
    assert c.post("/api/streamers", json={"name": "Valkyrae", "links": ["twitch.tv/valkyrae"]}).status_code == 422  # permission
    r = c.post("/api/streamers", json={"name": "Valkyrae", "links": ["https://www.twitch.tv/valkyrae", "https://kick.com/valkyrae"],
                                       "destination_ids": [tt, yt], "permission": True})
    assert r.status_code == 201, r.text
    v = r.json()
    assert v["destination_ids"] == [tt, yt] and v["watching"]
    assert sorted((ch["platform"], ch["username"]) for ch in v["channels"]) == [("kick", "valkyrae"), ("twitch", "valkyrae")]
    pages = {d["id"]: d for d in c.get("/api/destinations").json()}
    assert pages[tt]["creator_ids"] == [v["id"]] and pages[other]["creator_ids"] == []  # the other side matches
    # Her Twitch clips become videos for exactly her two pages.
    src = next(x for x in c.get("/api/sources").json() if x["platform"] == "twitch")
    soon = datetime.now(timezone.utc) + timedelta(seconds=5)
    fake.posts = [RemotePost("V1", "https://www.twitch.tv/valkyrae/clip/V1", "rae moment", posted_at=soon, views=900)]
    fake.origins["https://www.twitch.tv/valkyrae/clip/V1"] = ("https://www.twitch.tv/videos/7", 131.0)
    assert ctx.pipeline.check_source(src["id"])["new"] == 1
    drain(ctx)
    clip = c.get("/api/clips").json()[0]
    assert sorted(o["destination"]["id"] for o in clip["outputs"]) == sorted([tt, yt])


def test_change_pages_pause_and_remove_a_streamer(env):
    ctx, c, fake = env
    a = c.post("/api/destinations", json={"platform": "tiktok", "display_name": "A"}).json()["id"]
    b = c.post("/api/destinations", json={"platform": "tiktok", "display_name": "B"}).json()["id"]
    sid = c.post("/api/streamers", json={"name": "Lacy", "links": ["twitch.tv/lacy"], "destination_ids": [a], "permission": True}).json()["id"]
    assert c.patch(f"/api/streamers/{sid}", json={"destination_ids": [b]}).json()["destination_ids"] == [b]
    assert not c.patch(f"/api/streamers/{sid}", json={"watching": False}).json()["watching"]
    assert c.get("/api/sources").json()[0]["monitoring"] == "paused"
    # Swapping the link swaps the watched channel.
    ch = c.patch(f"/api/streamers/{sid}", json={"links": ["https://kick.com/lacy"]}).json()["channels"]
    assert [(x["platform"], x["username"]) for x in ch] == [("kick", "lacy")]
    c.delete(f"/api/streamers/{sid}")
    assert c.get("/api/streamers").json() == [] and c.get("/api/sources").json() == []
    assert all(d["creator_ids"] == [] for d in c.get("/api/destinations").json())


def test_pages_that_took_everyone_keep_doing_so_after_the_update():
    import tempfile
    import sqlalchemy as sa
    from alembic import command
    from alembic.config import Config as AC
    from clippr.db import MIGRATIONS_DIR, Database
    d = tempfile.mkdtemp()
    db = Database(f"sqlite:///{d}/t.db")
    cfg = AC()
    cfg.set_main_option("script_location", str(MIGRATIONS_DIR))
    with db.engine.begin() as conn:
        cfg.attributes["connection"] = conn
        command.upgrade(cfg, "0014")
        for i, n in ((1, "A"), (2, "B")):
            conn.execute(sa.text(f"INSERT INTO creators (id,name,color,notes,vod_channels,clip_permission,created_at) VALUES ({i},'{n}','#fff','','[]',1,'2026-01-01')"))
        conn.execute(sa.text("INSERT INTO destination_accounts (id,platform,external_id,display_name,handle,settings,enabled,creator_ids,created_at) "
                             "VALUES (1,'tiktok','m1','Any','','{}',1,'[]','2026-01-01'), (2,'tiktok','m2','Only B','','{}',1,'[2]','2026-01-01')"))
        conn.execute(sa.text("UPDATE destination_accounts SET creator_id = 2 WHERE id = 2"))
    db.migrate()
    with db.engine.connect() as conn:
        rows = dict(conn.execute(sa.text("SELECT id, creator_ids FROM destination_accounts")).all())
    assert rows[1] == "[1,2]" and rows[2] == "[2]"


def test_turning_on_watch_for_an_older_streamer_starts_watching_their_channel(env):
    ctx, c, fake = env
    cid = c.post("/api/creators", json={"name": "Old", "clip_permission": True, "vod_channels": ["https://www.twitch.tv/olds"]}).json()["id"]
    assert c.get("/api/streamers").json()[0]["channels"] == []
    v = c.patch(f"/api/streamers/{cid}", json={"watching": True}).json()
    assert v["watching"] and [(x["platform"], x["username"]) for x in v["channels"]] == [("twitch", "olds")]


def test_streamers_sharing_a_channel_can_both_be_watched(env):
    ctx, c, fake = env
    core = c.post("/api/streamers", json={"name": "The Core", "links": ["twitch.tv/silky"], "permission": True}).json()
    silky = c.post("/api/streamers", json={"name": "Silky", "links": ["twitch.tv/silky"], "permission": True}).json()
    assert core["watching"] and silky["watching"]
    assert [x["username"] for x in c.get("/api/sources").json()] == ["silky"]  # one channel, watched once
    off = c.patch(f"/api/streamers/{silky['id']}", json={"watching": False}).json()
    assert not off["watching"]  # the switch stays where it was put
    assert c.patch(f"/api/streamers/{silky['id']}", json={"watching": True}).json()["watching"]
    c.delete(f"/api/streamers/{silky['id']}")
    assert [x["username"] for x in c.get("/api/sources").json()] == ["silky"]  # The Core still uses it
    assert c.get("/api/streamers").json()[0]["channels"][0]["username"] == "silky"

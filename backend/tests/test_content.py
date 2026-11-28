"""What kind of clip it is: detection, routing to the right pages, and grading by kind."""
import numpy as np

from clippr import content
from clippr.grade import grade
from clippr.routing import for_kind

W, H = 960, 540
corner = [[(820, 400, 60, 60)]] * 12            # a small face fixed bottom right: a facecam
two = [[(200, 150, 140, 140), (600, 160, 140, 140)]] * 12  # two people at a table
one_big = [[(330, 80, 300, 300)]] * 12          # one person close to the camera
still, busy = np.full(20, 0.01), np.full(20, 0.09)


def test_category_decides_when_there_is_one():
    assert content.classify(game="Grand Theft Auto V", faces=None, motion=None, words=10, dur=20)["kind"] == "gaming"
    assert content.classify(game="Talk Shows & Podcasts", faces=None, motion=None, words=10, dur=20)["page_kind"] == "podcast"
    assert content.classify(game="IRL", faces=None, motion=None, words=10, dur=20)["page_kind"] == "regular"


def test_the_picture_decides_without_one():
    g = content.classify(game="", faces=(corner, (W, H)), motion=busy, words=20, dur=20)
    assert g["kind"] == "gaming" and g["signals"]["corner_cam"]
    p = content.classify(game="Just Chatting", faces=(two, (W, H)), motion=still, words=60, dur=20)
    assert p["kind"] == "podcast"
    c = content.classify(game="Just Chatting", faces=(one_big, (W, H)), motion=still, words=40, dur=20)
    assert c["kind"] == "chatting" and c["page_kind"] == "regular"
    i = content.classify(game="", faces=([[]] * 12, (W, H)), motion=np.full(20, 0.12), words=10, dur=20)
    assert i["kind"] == "irl"
    unsure = content.classify(game="", faces=None, motion=None, words=0, dur=20)
    assert unsure["confidence"] < 0.6  # not sure: the streamer's own kind is used instead


def test_pages_by_kind_never_lose_a_clip():
    pages = [(1, "tiktok", "Clips", "@vyralclips19", {"content_kinds": ["regular"]}),
             (2, "tiktok", "Games", "@vyralgames7", {"content_kinds": ["gaming"]}),
             (3, "instagram", "Pods", "@vyralpods", {"content_kinds": ["podcast"]})]
    assert [p[0] for p in for_kind(pages, "gaming", "regular")] == [1, 2]  # the general clips page takes gaming clips too
    assert [p[0] for p in for_kind(pages[1:], "regular", "regular")] == [1 + 1, 3]  # no general page: nothing fits, still posted
    assert [p[0] for p in for_kind(pages[2:], "gaming", "gaming")] == [3]  # a podcast-only page keeps none unless it's the only one
    assert [p[0] for p in for_kind(pages[:1], "podcast", "regular")] == [1]  # no podcast page: the streamer's kind
    assert [p[0] for p in for_kind(pages[1:2], "podcast", "regular")] == [2]  # nothing fits: still posted somewhere


def test_grading_checks_the_person_is_visible_for_the_kind():
    db = np.full(300, -25.0)
    db[100:120] = -8
    words = [(i * 0.4, i * 0.4 + 0.3, "word") for i in range(60)]
    part = lambda g: next(p for p in g.parts if p["name"] == "Picture")  # noqa: E731
    base = dict(db=db, words=words, length=30, has_captions=True, has_title=True, motion=busy)
    react = grade(**base, content={"kind": "gaming", "signals": {"corner_cam": True, "face_seen": 0.9, "face_size": 0.06}})
    blind = grade(**base, content={"kind": "gaming", "signals": {"corner_cam": False, "face_seen": 0.0, "face_size": 0.0}})
    assert part(react)["points"] > part(blind)["points"] and "no facecam" in part(blind)["note"]
    assert any("facecam" in t for t in blind.tips) or part(blind)["points"] >= 6
    assert sum(p["max"] for p in react.parts) == 100


def test_a_real_clip_gets_its_kind(env):
    from test_mcp import _clip
    ctx, c, fake = env
    cid, _, _ = _clip(ctx, c, fake)
    found = next(x for x in c.get("/api/clips").json() if x["id"] == cid)["content"]
    assert found["kind"] in ("gaming", "podcast", "irl", "chatting") and 0 <= found["confidence"] <= 1 and found["signals"]

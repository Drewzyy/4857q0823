"""The clip screener, learning from review notes, clearing all clips, and finding posts made on your pages."""
from datetime import datetime, timedelta, timezone

import numpy as np

from clippr import preedit, screen
from clippr.fetch import RemotePost
from clippr.media.overlay import Word
from clippr.models import Clip, ClipOutput, DestinationAccount


def _words(text, start=0.0, step=0.4):
    return [(start + i * step, start + i * step + 0.3, w) for i, w in enumerate(text.split())]


def test_screams_with_no_context_and_short_clips_are_held_back():
    lim = dict(screen.DEFAULTS)
    noise = _words("ahh haha bro what no no ahhh haha lmao bro " * 4)
    r = screen.check(noise, 45, lim)
    assert not r["pass"] and "Little is said" in r["reasons"][0]
    story = _words("so he walks up to the guy and asks if he can borrow his car for the race tonight and the guy actually says yes "
                   "then he drives it straight into the lake", 1.0, 0.5)
    assert screen.check(story, 45, lim)["pass"]
    short = screen.check(story, 20, lim)
    assert not short["pass"] and "Too short" in short["reasons"][0]
    late = _words("ahh haha bro " * 6) + _words("then he drives the car straight into the lake and everyone in chat loses it completely "
                                                "nobody saw that coming at all honestly and the streamer just sat there staring at the screen for a while", 23.0, 0.3)
    assert any("No setup" in x for x in screen.check(late, 45, lim)["reasons"])


def test_review_notes_move_the_limits_and_reset_puts_them_back(ctx):
    with ctx.db.session() as s:
        assert screen.learn(s, "this clip is too short", 1) == {"min_seconds": [35.0, 38.0], "setup_words": [8, 10]}
        screen.learn(s, "boring, nothing happens")
        screen.learn(s, "great clip")  # says nothing usable: no change
    with ctx.db.session() as s:
        got = screen.learned(s)
        assert got["min_seconds"] == 38.0 and got["min_score"] == 3 and len(got["history"]) == 2
        for _ in range(20):
            screen.learn(s, "too short")
        assert screen.learned(s)["min_seconds"] == 60.0  # never past its limit
        screen.reset(s)
    with ctx.db.session() as s:
        assert screen.learned(s)["min_seconds"] == 35.0


def test_the_headline_shows_for_the_opening_seconds_only():
    words = [Word(i * 0.5, i * 0.5 + 0.4, "word") for i in range(80)]
    db = np.full(400, -30.0)
    db[300:320] = -5
    e = preedit.apply({"start": 0.0, "end": 40.0, "texts": []}, words, db, "Kai couldn't believe it", hook=False, named=True)
    head = next(x for x in e["texts"] if x.get("headline"))
    assert head["end"] <= preedit.TITLE_SECONDS + 0.01 and head["y_percent"] == preedit.HEADLINE_Y and head["box"]
    assert e["end"] - e["start"] >= 25


def _clip(ctx, tmp_path, n=2):
    ids = []
    with ctx.db.session() as s:
        d = DestinationAccount(platform="tiktok", external_id="mypage", handle="@mypage", display_name="My page", settings={})
        s.add(d)
        s.flush()
        for i in range(n):
            folder = tmp_path / f"c{i}"
            folder.mkdir()
            (folder / "render-0.mp4").write_bytes(b"x")
            c = Clip(expires_at=datetime.now(timezone.utc) + timedelta(days=9), files_dir=str(folder), title=f"Clip {i}")
            s.add(c)
            s.flush()
            s.add(ClipOutput(clip_id=c.id, destination_id=d.id, platform="tiktok", file_path=str(folder / "render-0.mp4"),
                             title=f"Kai could not stop laughing at the chat {i}", review="approved",
                             description=f"Kai could not stop laughing at the chat {i} 😭 #kai #fyp"))
            ids.append(c.id)
    return ids


def test_clear_all_needs_the_phrase_and_removes_every_clip(ctx, client, tmp_path):
    _clip(ctx, tmp_path)
    assert client.post("/api/clips/clear-all", json={"confirm": "yes"}).status_code == 422
    assert client.post("/api/clips/clear-all", json={"confirm": "DELETE ALL CLIPS"}).json() == {"deleted": 2}
    assert client.get("/api/clips").json() == [] and not (tmp_path / "c0").exists()


def test_posts_on_your_page_are_linked_to_their_clips_by_length(ctx, tmp_path, monkeypatch):
    from clippr.media.ffmpeg import run
    _clip(ctx, tmp_path)
    for i, secs in enumerate((12, 20)):  # two clips, same caption style: told apart by their length
        run(["-y", "-f", "lavfi", "-i", f"color=c=gray:size=64x64:rate=10:duration={secs}", "-c:v", "libx264", "-preset", "ultrafast",
             "-f", "mp4", str(tmp_path / f"c{i}" / "render-0.mp4")])
    later = datetime.now(timezone.utc) + timedelta(minutes=5)
    listed = [RemotePost("1", "https://www.tiktok.com/@mypage/video/1", "@kai #kai #fyp"),  # the page list has no lengths
              RemotePost("2", "https://www.tiktok.com/@mypage/video/2", "@kai #kai #fyp", posted_at=later, duration=33)]
    full = {"https://www.tiktok.com/@mypage/video/1": RemotePost("1", "https://www.tiktok.com/@mypage/video/1", "@kai #kai #fyp",
                                                                 posted_at=later, duration=20.3)}
    monkeypatch.setattr(ctx.fetcher, "recent_posts", lambda *a, **k: listed, raising=False)
    monkeypatch.setattr(ctx.fetcher, "post_details", lambda url: full[url], raising=False)
    assert ctx.pipeline.detect_posts() == {"linked": 1}  # the 33 s post matches no clip
    with ctx.db.session() as s:
        linked = [o for o in s.query(ClipOutput).all() if o.post_url]
        assert len(linked) == 1 and linked[0].post_url.endswith("/video/1") and linked[0].status == "uploaded"
        assert linked[0].file_path.endswith("c1/render-0.mp4") and linked[0].post_check["by"] == "auto-detected"
    assert ctx.pipeline.detect_posts() == {"linked": 0}  # never linked twice


def test_captions_tag_the_streamers_channel_not_their_name(ctx):
    from clippr.models import Creator, SourceAccount
    from clippr.pipeline import streamer_handle
    with ctx.db.session() as s:
        c = Creator(name="Jason Levine")
        s.add(c)
        s.flush()
        assert streamer_handle(c) == "Jason Levine"  # nothing else known yet
        s.add(SourceAccount(platform="twitch", username="jasontheween", profile_url="https://www.twitch.tv/jasontheween",
                            creator_id=c.id, creator_ids=[c.id]))
        s.flush()
        assert streamer_handle(c) == "jasontheween"


def test_a_post_link_must_open_a_live_post_on_that_page(ctx, client, tmp_path, monkeypatch):
    from clippr.fetch import FetchError
    _clip(ctx, tmp_path, n=1)
    with ctx.db.session() as s:
        oid = s.query(ClipOutput).one().id
    def details(url):
        if url.endswith("/404"):
            raise FetchError("This video is unavailable")
        if url.endswith("/offline"):
            raise FetchError("Connection reset")
        who = "someoneelse" if "someoneelse" in url else "mypage"
        return RemotePost("9", url, "Kai could not stop laughing", channels=(who,))
    monkeypatch.setattr(ctx.fetcher, "post_details", details, raising=False)
    r = client.put(f"/api/outputs/{oid}/post", json={"post_url": "https://www.tiktok.com/@mypage/video/404"})
    assert r.status_code == 422 and "live post" in r.json()["error"]["message"]
    r = client.put(f"/api/outputs/{oid}/post", json={"post_url": "https://www.tiktok.com/@someoneelse/video/1"})
    assert r.status_code == 422 and "not this page" in r.json()["error"]["message"]
    r = client.put(f"/api/outputs/{oid}/post", json={"post_url": "https://www.tiktok.com/@mypage/video/offline"})
    assert r.json()["post_check"]["status"] == "unverified"  # couldn't check now: kept, checked again later
    monkeypatch.setattr(ctx.fetcher, "post_details", lambda url: (_ for _ in ()).throw(FetchError("Video not found")), raising=False)
    assert ctx.pipeline.verify_posts() == {"checked": 1, "refused": 1}  # turned out not to exist: taken back
    with ctx.db.session() as s:
        o = s.get(ClipOutput, oid)
        assert o.post_url is None and o.status == "ready" and o.post_check["status"] == "failed"
    hist = client.get("/api/posted").json()
    assert hist[0]["status"] == "failed" and hist[0]["by"] == "you"
    monkeypatch.setattr(ctx.fetcher, "post_details", details, raising=False)
    r = client.put(f"/api/outputs/{oid}/post", json={"post_url": "https://www.tiktok.com/@mypage/video/7"})
    assert r.json()["post_check"]["status"] == "verified" and client.get("/api/posted").json()[0]["status"] == "verified"


def test_chants_and_flat_clips_are_held_back():
    lim = dict(screen.DEFAULTS)
    chant = _words("let's go let's go chat let's go let's go chat " * 4, 0.5, 0.5)
    assert any("same few words" in x for x in screen.check(chant, 45, lim)["reasons"])
    story = _words("so he walks up to the guy and asks if he can borrow his car for the race tonight and the guy actually says yes "
                   "then he drives it straight into the lake", 1.0, 0.5)
    flat = [{"name": "Energy and emotion", "points": 2, "max": 15}, {"name": "Ends on the payoff", "points": 1, "max": 5}]
    assert any("Flat" in x for x in screen.check(story, 45, lim, flat)["reasons"])
    lively = [{"name": "Energy and emotion", "points": 12, "max": 15}, {"name": "Ends on the payoff", "points": 4, "max": 5}]
    assert screen.check(story, 45, lim, lively)["pass"]


def test_the_picture_is_checked_for_nudity(tmp_path):
    from clippr import safety
    from clippr.media import nsfw
    from clippr.media.ffmpeg import run
    v = tmp_path / "game.mp4"
    run(["-f", "lavfi", "-i", "testsrc2=size=640x360:rate=30:duration=6", "-c:v", "libx264", "-preset", "ultrafast", str(v)])
    got = nsfw.scan(v, 0, 6)
    assert got["level"] == "pass" and got["max"] is not None and got["max"] < nsfw.REVIEW
    base = dict(permission=True, words=[], texts=["a title"])
    out = safety.check(**base, picture={"max": 0.97, "at": 3.0, "hits": 3, "level": "fail"})
    assert out["status"] == "fail" and out["flags"][0]["category"] == "sexual content and nudity" and out["flags"][0]["at"] == 3.0
    assert not any(x.startswith("the picture") for x in out["not_checked"])
    assert safety.check(**base, picture={"max": 0.7, "at": 1.0, "hits": 0, "level": "review"})["status"] == "review"
    assert safety.check(**base, picture=got)["status"] == "pass"


def test_titles_never_swear_or_say_only_a_reaction():
    from clippr import titles
    from clippr.media.overlay import Word
    def w(s):
        return [Word(i * 0.4, i * 0.4 + 0.3, x) for i, x in enumerate(s.split())]
    for line in ["what the fuck!", "oh my god no way bro.", "no way he actually did that right now!", "bro this is so fucking good"]:
        title, quoted = titles.make_title(w(line), "Kai", 1.0)
        assert not quoted and not titles.PROFANE.search(title), (line, title)
    title, quoted = titles.make_title(w("he just sold my sword for a sandwich!"), "Kai", 1.0)
    assert quoted and "he just sold my sword for a sandwich" in title and "!" not in title


def test_swearing_is_bleeped_and_starred_out(tmp_path):
    from clippr import titles
    from clippr.media.ffmpeg import probe, run
    from clippr.media.render import OutputFormat, render
    assert titles.censor("what the fuck, that's fucking shit") == "what the f***, that's f****** s***"
    src = tmp_path / "s.mp4"
    run(["-f", "lavfi", "-i", "testsrc2=size=320x180:rate=30:duration=4", "-f", "lavfi", "-i", "sine=f=220:d=4",
         "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", str(src)])
    out = render(src, tmp_path / "o.mp4", OutputFormat(180, 320, 30), duration=4, bleeps=[(1.0, 1.4), (2.5, 2.8)], use_hardware=False)
    info = probe(out)
    assert info.has_audio and abs(info.duration - 4) < 0.3


def test_two_people_talking_each_get_a_view_and_face_only_fills_the_frame(tmp_path):
    from clippr.media import facecam
    from clippr.media.ffmpeg import probe, run
    from clippr.media.render import OutputFormat, render
    size = (960, 540)
    frames = [[(150, 150, 110, 110), (700, 160, 100, 100)] for _ in range(10)] + [[(150, 150, 110, 110)]] * 2
    box, pan = facecam.two_people(frames, size, 16 / 9, 1080 / (1920 * 0.4), 0.527)
    assert box[0] < 0.3 and pan > 0.8  # the left person on top, the bottom pointed at the right person
    assert facecam.two_people([[(150, 150, 110, 110)]] * 10, size, 16 / 9, 1.4, 0.527) is None  # one person: no split
    src = tmp_path / "s.mp4"
    run(["-f", "lavfi", "-i", "testsrc2=size=640x360:rate=30:duration=2", "-c:v", "libx264", "-preset", "ultrafast", str(src)])
    out = render(src, tmp_path / "f.mp4", OutputFormat(1080, 1920, 30), duration=2, face=[0.7, 0.6, 0.25, 0.35], use_hardware=False)
    info = probe(out)
    assert (info.width, info.height) == (1080, 1920)


def test_only_the_best_few_clips_of_a_streamer_go_out_each_day(ctx):
    from clippr import posting
    from clippr.api.system import SETTINGS_KEY
    from clippr.models import Creator, Setting
    with ctx.db.session() as s:
        s.merge(Setting(key=SETTINGS_KEY, value={"posting": {"per_streamer_day": 2}}))
        cr = Creator(name="Kai", clip_permission=True)
        s.add(cr)
        s.flush()
        clips = []
        for score in (60, 90, 75):
            c = Clip(creator_id=cr.id, expires_at=datetime.now(timezone.utc) + timedelta(days=9),
                     grade={"score": score, "screen": {"pass": True}}, safety={"status": "pass"})
            s.add(c)
            s.flush()
            clips.append(c)
        assert posting.held_back(clips[1], 50) is None and posting.held_back(clips[2], 50) is None
        assert "2 best clips of Kai" in posting.held_back(clips[0], 50)


def test_fed_pages_get_the_best_of_other_pages(ctx, tmp_path, monkeypatch):
    from clippr.models import MetricSnapshot
    ids = _clip(ctx, tmp_path, n=4)
    with ctx.db.session() as s:
        ig = s.query(DestinationAccount).one()
        tt = DestinationAccount(platform="tiktok", external_id="games", handle="@vyralgames", display_name="vyral games",
                                settings={"feeds_from": [ig.id], "top_percent": 25})
        s.add(tt)
        s.flush()
        for n, o in enumerate(s.query(ClipOutput).order_by(ClipOutput.id)):
            src = tmp_path / f"src{n}.mp4"
            src.write_bytes(b"x")
            s.get(Clip, o.clip_id).source_path = str(src)
            o.status, o.post_url = "uploaded", f"https://www.instagram.com/reel/{n}/"
            o.uploaded_at = datetime.now(timezone.utc) - timedelta(hours=10)
            s.add(MetricSnapshot(output_id=o.id, views=[100, 5000, 300, 200][n], source="muse"))
        tt_id = tt.id
    assert ctx.pipeline.promote_best() == {"promoted": 1}
    with ctx.db.session() as s:
        [o] = s.query(ClipOutput).filter(ClipOutput.destination_id == tt_id).all()
        assert o.clip_id == ids[1] and o.review == "approved" and o.render_state == "rendering"
    assert ctx.pipeline.promote_best() == {"promoted": 0}  # never twice


def test_gameplay_with_nudity_switches_to_the_streamers_face(ctx, tmp_path, monkeypatch):
    from clippr.media import nsfw
    from clippr.models import Creator
    src = tmp_path / "src.mp4"
    src.write_bytes(b"x")
    with ctx.db.session() as s:
        cr = Creator(name="Kai", clip_permission=True, facecam=[0.7, 0.6, 0.25, 0.35])
        s.add(cr)
        s.flush()
        c = Clip(creator_id=cr.id, expires_at=datetime.now(timezone.utc) + timedelta(days=9), source_path=str(src),
                 source_start=0, source_duration=40, edit={"start": 0, "end": 40, "layout": "normal"})
        s.add(c)
        s.flush()
        cid = c.id
    monkeypatch.setattr(nsfw, "scan", lambda path, a, d, region=None: {"max": 0.1, "at": None, "hits": 0, "level": "pass"} if region
                        else {"max": 0.97, "at": 12.0, "hits": 4, "level": "fail"})
    out = ctx.pipeline.check_safety(cid)
    assert out["status"] == "review" and any("only the streamer's face" in f["reason"] for f in out["flags"])
    with ctx.db.session() as s:
        assert s.get(Clip, cid).edit["layout"] == "face"


def test_muse_reports_instagram_numbers(ctx, tmp_path):
    from clippr import mcp
    from clippr.models import MetricSnapshot
    [cid] = _clip(ctx, tmp_path, n=1)
    with ctx.db.session() as s:
        s.query(Clip).one().edit = {"start": 0, "end": 40}
    try:
        mcp.report_metrics(ctx, {"clip_id": cid, "views": 1200})
        raise AssertionError("needs the post first")
    except mcp.ToolError as e:
        assert "mark_posted" in str(e)
    with ctx.db.session() as s:
        s.query(ClipOutput).one().post_url = "https://www.instagram.com/reel/abc/"
    assert mcp.report_metrics(ctx, {"clip_id": cid, "views": 1200, "likes": 80})["recorded"] == {"views": 1200, "likes": 80}
    with ctx.db.session() as s:
        assert s.query(MetricSnapshot).one().source == "muse"

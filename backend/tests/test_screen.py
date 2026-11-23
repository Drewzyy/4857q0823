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


def test_posts_on_your_page_are_linked_to_their_clips(ctx, tmp_path, monkeypatch):
    _clip(ctx, tmp_path)
    posts = [RemotePost("1", "https://www.tiktok.com/@mypage/video/1", "Kai could not stop laughing at the chat 1 😭 #kai"),
             RemotePost("2", "https://www.tiktok.com/@mypage/video/2", "something else entirely")]
    monkeypatch.setattr(ctx.fetcher, "recent_posts", lambda *a, **k: posts, raising=False)
    assert ctx.pipeline.detect_posts() == {"linked": 1}
    with ctx.db.session() as s:
        linked = [o for o in s.query(ClipOutput).all() if o.post_url]
        assert len(linked) == 1 and linked[0].post_url.endswith("/video/1") and linked[0].status == "uploaded"
    assert ctx.pipeline.detect_posts() == {"linked": 0}  # never linked twice


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

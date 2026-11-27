"""The clip screener, learning from review notes, clearing all clips, and finding posts made on your pages."""
from datetime import datetime, timedelta, timezone

from pathlib import Path

import numpy as np

from clippr import preedit, screen
from clippr.fetch import RemotePost
from clippr.media.overlay import Word
from sqlalchemy import select
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



def test_clear_short_removes_only_unposted_clips_under_the_floor(ctx, client, tmp_path):
    ids = _clip(ctx, tmp_path, n=4)
    with ctx.db.session() as s:
        for cid, secs, posted in zip(ids, (6, 45, 8, None), (False, False, True, False)):
            o = s.scalars(select(ClipOutput).where(ClipOutput.clip_id == cid)).one()
            o.quality = {"status": "pass", "measures": {"duration": secs}} if secs else None
            o.post_url = "https://www.tiktok.com/@mypage/video/1" if posted else None
    assert client.post("/api/clips/clear-short").json() == {"deleted": 1, "kept_posted": 1, "under": 20.0}
    left = {c["id"] for c in client.get("/api/clips").json()}
    assert left == set(ids[1:]) and not (tmp_path / "c0").exists()  # unreadable length (the fake file): kept

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
        assert Path(linked[0].file_path).parent.name == "c1" and linked[0].post_check["by"] == "auto-detected"
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


def test_captions_already_in_the_footage_are_found(tmp_path):
    from clippr.media import onscreen
    from clippr.media.ffmpeg import run
    font = next((Path(__file__).parent.parent / "clippr" / "media" / "fonts").glob("*.ttf"))
    ff = str(font).replace("\\", "/").replace(":", "\\:")
    words = ["NO WAY HE", "ACTUALLY DID", "THAT RIGHT", "NOW BRO", "LOOK AT", "THE CAR GO", "INTO THE", "LAKE OMG"]
    caps = ",".join(f"drawtext=fontfile='{ff}':text='{w}':fontsize=54:fontcolor=yellow:borderw=5:bordercolor=black:"
                    f"x=(w-tw)/2:y=h*0.36:enable='between(t,{i * 2},{i * 2 + 2})'" for i, w in enumerate(words))
    base = ["-f", "lavfi", "-i", "testsrc2=size=1280x720:rate=10:duration=16"]
    with_caps, titled, plain = tmp_path / "c.mp4", tmp_path / "t.mp4", tmp_path / "p.mp4"
    run([*base, "-vf", caps, "-c:v", "libx264", "-preset", "ultrafast", str(with_caps)])
    run([*base, "-vf", f"drawtext=fontfile='{ff}':text='SAME TITLE ALL CLIP':fontsize=54:fontcolor=white:borderw=5:x=(w-tw)/2:y=h*0.7",
         "-c:v", "libx264", "-preset", "ultrafast", str(titled)])
    run([*base, "-c:v", "libx264", "-preset", "ultrafast", str(plain)])
    assert onscreen.has_captions(with_caps, 0, 16)  # just above the middle, like TikTok reposts: found
    assert not onscreen.has_captions(titled, 0, 16)  # a fixed line is a title, not captions
    assert not onscreen.has_captions(plain, 0, 16)


def _made_clip(tmp_path):
    """A vertical clip edited like yours: the climax first (3 s that come back at 17 s), facecam panel on top and the
    game under it, a headline at the top for the first 4 s, captions that change, Vyral's boom twice, a punch-in at 25 s."""
    from clippr.media import sfx
    from clippr.media.ffmpeg import run
    from media_fixtures import SR, speechlike, write_wav
    talk = speechlike(36, 7)
    wav = write_wav(tmp_path / "a.wav", np.concatenate([talk[int(14 * SR):int(17 * SR)], talk]))
    boom = sfx.path("boom", tmp_path / "sfx")
    font = next((Path(__file__).parent.parent / "clippr" / "media" / "fonts").glob("*.ttf")).as_posix().replace(":", "\\:")  # Windows too
    caps = ",".join(f"drawtext=fontfile='{font}':text='{w}':fontsize=70:fontcolor=white:borderw=6:x=(w-tw)/2:y=h*0.72:"
                    f"enable='between(t,{i * 3},{i * 3 + 3})'" for i, w in enumerate(["NO WAY", "HE DID", "THAT TO", "THE CAR", "AND THEN",
                                                                                       "IT FELL", "OFF THE", "BRIDGE", "LOOK AT", "HIM GO", "OH NO", "BRO"]))
    head = f"drawtext=fontfile='{font}':text='HE THOUGHT IT WAS FINE':fontsize=64:fontcolor=black:box=1:boxcolor=white:boxborderw=20:x=(w-tw)/2:y=h*0.1:enable='lt(t,4)'"
    out = tmp_path / "made.mp4"
    run(["-f", "lavfi", "-i", "color=c=0x404060:size=1080x768:rate=15:duration=39", "-f", "lavfi", "-i", "testsrc2=size=1080x1152:rate=15:duration=39",
         "-i", str(wav), "-i", str(boom), "-filter_complex",
         "[1:v]split[g][gz];[gz]crop=iw/1.3:ih/1.3,scale=1080:1152[z];[g][z]overlay=enable='gte(t,25)'[game];"
         f"[0:v][game]vstack,{head},{caps}[v];[3:a]asplit[b1][b2];[b1]adelay=20000|20000[s1];[b2]adelay=28000|28000[s2];"
         "[2:a][s1][s2]amix=inputs=3:duration=first:normalize=0[a]", "-map", "[v]", "-map", "[a]",
         "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", "-shortest", str(out)])
    return out


def test_your_clips_are_measured_and_new_clips_follow_your_style(ctx, tmp_path):
    from clippr import style
    got = style.analyze(_made_clip(tmp_path))
    assert 38 <= got["length"] <= 40 and got["hook"] >= 2 and got["layout"] == "stacked" and got["captions"]
    assert 3 <= got["headline"] <= 6 and got["sfx"] >= 1 and got["sound"] == "boom" and got["zooms"] >= 1, got
    with ctx.db.session() as s:
        for i in range(2):
            assert style.add(s, f"https://www.tiktok.com/@me/video/{i}", got) is None  # not enough yet
        p = style.add(s, "https://www.tiktok.com/@me/video/2", got)
    assert p["examples"] == 3 and p["hook_rate"] == 1 and p["layout"] == "stacked" and p["headline_rate"] == 1


def test_a_plain_clip_measures_as_plain(tmp_path):
    from clippr import style
    from clippr.media.ffmpeg import run
    from media_fixtures import speechlike, write_wav
    wav = write_wav(tmp_path / "p.wav", speechlike(30, 3))
    out = tmp_path / "plain.mp4"
    run(["-f", "lavfi", "-i", "testsrc2=size=1080x1920:rate=15:duration=30", "-i", str(wav), "-c:v", "libx264", "-preset", "ultrafast",
         "-c:a", "aac", "-shortest", str(out)])
    got = style.analyze(out)
    assert got["hook"] == 0 and got["headline"] == 0 and not got["captions"] and got["sfx"] == 0 and got["sound"] is None, got
    assert got["zooms"] == 0 and got["layout"] in ("full", "stacked"), got


def test_a_learned_style_changes_how_clips_are_cut():
    from clippr.media.overlay import Word
    words = [Word(i * 0.5, i * 0.5 + 0.4, "word") for i in range(140)]
    db = np.full(700, -30.0)
    db[500:520] = -5
    mine = {"examples": 5, "length": 30.0, "length_low": 28.0, "length_high": 32.0, "hook_rate": 0.0, "hook_seconds": 0.0,
            "cuts_per_min": 2, "layout": "full", "layouts": {"full": 5}, "captions_rate": 0.0, "headline_rate": 1.0,
            "headline_seconds": 8.0, "sfx_rate": 0.0}
    e = preedit.apply({"start": 0.0, "end": 70.0, "texts": []}, words, db, "kai lost it", sound=True, hook=True, style=mine)
    assert 27 <= e["end"] - e["start"] <= 33 and not e.get("hook") and not e.get("sounds") and e["captions"] is False
    head = next(x for x in e["texts"] if x.get("headline"))  # nearly all of yours have one: so does this one, for 8 s
    assert head["end"] == 8.0


def test_clips_sent_to_the_inbox_are_learned_from(ctx, tmp_path, monkeypatch):
    from clippr import style
    made = _made_clip(tmp_path)
    monkeypatch.setattr(ctx.fetcher, "download_post", lambda url, dest: made, raising=False)
    got = style.learn(ctx, "https://www.tiktok.com/@me/video/1")
    assert got["features"]["layout"] == "stacked" and got["profile"] is None
    assert style.learn(ctx, "https://www.tiktok.com/@me/video/1") == {"skipped": "already learned"}
    monkeypatch.setattr(ctx.fetcher, "download_post", lambda url, dest: (_ for _ in ()).throw(RuntimeError("private")), raising=False)
    assert style.learn(ctx, "https://www.tiktok.com/@me/video/2")["error"] == "private"


def test_clips_with_more_views_count_for_more_and_the_style_picks_your_sound():
    from clippr import style
    from clippr.media.overlay import Word
    short = {"length": 30, "hook": 0, "cuts_per_min": 1, "layout": "full", "captions": True, "headline": 0, "sfx": 0, "sound": None, "zooms": 0}
    long = {**short, "length": 60, "hook": 3.0, "sfx": 2, "sound": "boom", "zooms": 2}
    ex = [{"url": f"u{i}", "features": short, "views": 50} for i in range(3)] + [{"url": "big", "features": long, "views": 2_000_000},
                                                                                {"url": "big2", "features": long, "views": 900_000}]
    p = style.profile_of(ex)
    assert p["length"] == 60 and p["hook_rate"] > 0.5 and p["sound"] == "boom" and p["zoom_rate"] > 0.5  # the hits win
    words = [Word(i * 0.5, i * 0.5 + 0.4, "word") for i in range(160)]
    db = np.full(800, -30.0)
    db[600:615] = -2
    e = preedit.apply({"start": 0.0, "end": 80.0, "texts": []}, words, db, "", sound=True, hook=False, style=p)
    assert e.get("sounds") and e["sounds"][0]["name"] == "boom" and e.get("punch")
    p0 = style.profile_of([{"url": f"u{i}", "features": short} for i in range(3)])
    assert not preedit.apply({"start": 0.0, "end": 80.0, "texts": []}, words, db, "", sound=True, style=p0).get("punch")


def test_hashtags_songs_and_the_cut_are_learned_and_posts_wait_for_daytime(ctx, tmp_path, monkeypatch):
    from clippr import describe, posting, style
    from clippr.fetch import RemotePost
    from clippr.media.overlay import Word
    from clippr.schemas import PostingSettings
    made = _made_clip(tmp_path)
    monkeypatch.setattr(ctx.fetcher, "download_post", lambda url, dest: made, raising=False)
    monkeypatch.setattr(ctx.fetcher, "post_details", lambda url: RemotePost(
        "1", url, "togi did it again #togi #kickstreaming #fyp", views=40000, music="Shake It - Some Artist"), raising=False)
    for i in range(3):
        got = style.learn(ctx, f"https://www.tiktok.com/@me/video/{i}")
    assert got["hashtags"] == ["#fyp", "#kickstreaming", "#togi"] and got["song"] == "Shake It - Some Artist"
    p = got["profile"]
    assert p["hashtags"] == ["#kickstreaming", "#togi"] and p["songs"] == ["Shake It - Some Artist"]
    assert p["peak_share"] is not None and p["tail"] is not None
    _, cap = describe.build("tiktok", "t", "", {"learned_tags": p["hashtags"]}, streamer="togi")
    assert cap == "@togi #togi #fyp #funny #kickstreaming"
    # Cut like yours: the moment at the same place, the same tail after it.
    words = [Word(i * 0.5, i * 0.5 + 0.4, "word.") for i in range(300)]
    db = np.full(1500, -30.0)
    db[1000:1015] = -2  # the moment at 100 s of 150
    mine = {**p, "length": 40.0, "length_low": 35.0, "length_high": 45.0, "tail": 6.0, "peak_share": 0.85}
    a, b = preedit.best_window(db, words, 150.0, style=mine)
    assert 100 < b <= 107 and 35 <= b - a <= 45
    cfg = PostingSettings(post_from=12, post_until=22)
    late = datetime(2026, 11, 25, 23, 40).astimezone()  # 11:40 pm here
    nxt = posting.in_window(late.astimezone(timezone.utc), cfg).astimezone()
    assert nxt.hour == 12 and nxt.date() > late.date()
    noon = datetime(2026, 11, 25, 15, 0).astimezone()
    assert posting.in_window(noon, cfg) == noon


def test_vyral_keeps_what_gets_more_views_on_your_pages(ctx, tmp_path):
    import random
    from clippr import tuner
    from clippr.media.overlay import Word
    from clippr.models import MetricSnapshot
    # Every clip records what it got; one in four tries something else.
    words = [Word(i * 0.5, i * 0.5 + 0.4, "word") for i in range(160)]
    db = np.full(800, -30.0)
    db[600:615] = -2
    e = preedit.apply({"start": 0.0, "end": 80.0, "texts": []}, words, db, "", sound=True, hook=True, force={"zoom": False, "length": -10})
    assert e["trial"]["zoom"] is False and e["trial"]["length"] == -10 and not e.get("punch")
    with ctx.db.session() as s:
        picks = [tuner.pick(s, random.Random(i)) for i in range(400)]
    assert 0.18 < sum(1 for p in picks if p.get("exploring")) / 400 < 0.32
    # 16 posts on one page: the 10 s shorter ones get about twice the views an hour.
    ids = _clip(ctx, tmp_path, n=16)
    with ctx.db.session() as s:
        for n, o in enumerate(s.query(ClipOutput).order_by(ClipOutput.id)):
            shorter = n % 2 == 0
            s.get(Clip, o.clip_id).edit = {"trial": {"hook": True, "headline": False, "sfx": True, "zoom": True, "length": -10 if shorter else 0}}
            o.status, o.uploaded_at = "uploaded", datetime.now(timezone.utc) - timedelta(hours=24)
            s.add(MetricSnapshot(output_id=o.id, views=(4800 if shorter else 2400) + n * 10, source="auto"))
    assert ids
    with ctx.db.session() as s:
        got = tuner.learn(s)
    assert got["best"] == {"length": -10} and got["results"]["length"]["-10"]["posts"] == 8
    with ctx.db.session() as s:
        assert all(p.get("length") == -10 or p.get("exploring") == "length" for p in (tuner.pick(s, random.Random(i)) for i in range(50)))


def test_the_companion_extension_gets_due_videos_and_reports_back(ctx, tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from clippr import mcp
    from clippr.fetch import RemotePost
    ids = _clip(ctx, tmp_path, n=2)
    with ctx.db.session() as s:
        for o in s.query(ClipOutput).all():
            c = s.get(Clip, o.clip_id)
            c.grade, c.safety = {"score": 80, "screen": {"pass": True}}, {"status": "pass"}
            o.render_state, o.quality = "ready", {"status": "pass"}
        s.query(ClipOutput).filter(ClipOutput.clip_id == ids[1]).one().review = "pending"  # not approved: never offered
    monkeypatch.setattr("clippr.posting.probe", lambda p: type("I", (), {"duration": 40.0})(), raising=False)
    monkeypatch.setattr("clippr.media.ffmpeg.probe", lambda p: type("I", (), {"duration": 40.0})())
    monkeypatch.setattr("clippr.posting.in_window", lambda when, cfg: when)  # whatever the time of day the test runs
    api = TestClient(mcp.create_app(ctx), base_url="http://127.0.0.1:47821")
    tok = {"Authorization": f"Bearer {mcp.token(ctx)}"}
    assert api.get("/companion/next").status_code == 401
    job = api.get("/companion/next", headers=tok).json()["job"]
    assert job["platform"] == "tiktok" and job["upload_page"].startswith("https://www.tiktok.com") and job["auto"] is False
    v = api.get(job["video"], headers={**tok, "Origin": "https://www.tiktok.com"})
    assert v.status_code == 200 and "access-control-allow-origin" not in v.headers  # no website reads it: only the extension
    assert api.get(job["video"]).status_code == 401
    # It couldn't post (a captcha): that video waits an hour, and nothing else is due.
    assert api.post("/companion/result", headers=tok, json={"output_id": job["output_id"], "posted": False, "reason": "captcha"}).json() == {"ok": True}
    assert api.get("/companion/next", headers=tok).json()["job"] is None
    with ctx.db.session() as s:
        s.get(ClipOutput, job["output_id"]).post_check = None
    monkeypatch.setattr(ctx.fetcher, "post_details", lambda url: RemotePost("9", url, "x", channels=("mypage",)), raising=False)
    r = api.post("/companion/result", headers=tok, json={"output_id": job["output_id"], "posted": True,
                                                          "post_url": "https://www.tiktok.com/@mypage/video/9"}).json()
    assert r["recorded"] and r["post_check"]["status"] == "verified"
    with ctx.db.session() as s:
        o = s.get(ClipOutput, job["output_id"])
        assert o.status == "uploaded" and o.post_url.endswith("/video/9")


def test_the_extension_is_handed_out_from_settings(client, tmp_path, monkeypatch):
    monkeypatch.setenv("CLIPPR_DOWNLOADS_DIR", str(tmp_path / "dl"))
    where = Path(client.post("/api/companion/extension").json()["path"])
    assert (where / "manifest.json").exists() and (where / "sites" / "tiktok.js").exists()


def test_a_post_waiting_for_you_pings_discord(ctx, tmp_path):
    from fastapi.testclient import TestClient
    from clippr import mcp
    from clippr.models import Event
    _clip(ctx, tmp_path, n=1)
    with ctx.db.session() as s:
        oid = s.query(ClipOutput).one().id
    api = TestClient(mcp.create_app(ctx), base_url="http://127.0.0.1:47821")
    tok = {"Authorization": f"Bearer {mcp.token(ctx)}"}
    for _ in range(2):  # once per video
        assert api.post("/companion/result", headers=tok, json={"output_id": oid, "attention": True, "text": "filled in, press Post"}).json() == {"ok": True}
    api.post("/companion/result", headers=tok, json={"output_id": oid, "attention": True, "stopped": True, "text": "The site is showing a captcha"})
    with ctx.db.session() as s:
        evs = s.query(Event).order_by(Event.id).all()
        assert [e.title for e in evs] == ["Post ready on TikTok: press Post", "Vyral Companion stopped on TikTok: needs you"]
        assert evs[0].category == "approvals" and "My page" in evs[0].body and evs[1].priority == "urgent"


def test_post_it_from_your_phone_with_the_link_in_the_ping(ctx, tmp_path):
    from fastapi.testclient import TestClient
    from clippr import companion, mcp
    from clippr.models import Event
    _clip(ctx, tmp_path, n=1)
    with ctx.db.session() as s:
        oid = s.query(ClipOutput).one().id
    ctx.mcp.host, ctx.mcp.port = "100.115.250.79", 47821  # the bridge on Tailscale, as for Muse
    host = "http://100.115.250.79:47821"
    api = TestClient(mcp.create_app(ctx), base_url=host)
    tok = {"Authorization": f"Bearer {mcp.token(ctx)}"}
    api.post("/companion/result", headers=tok, json={"output_id": oid, "attention": True, "text": "filled in"})
    with ctx.db.session() as s:
        ev = s.query(Event).one()
        link = ev.link
    assert link.startswith(f"{host}/go/{oid}/") and "phone" in ev.body
    path = link.removeprefix(host)
    assert api.get(f"/companion/pressed/{oid}", headers=tok).json() == {"pressed": False}
    page = api.get(path)
    assert "Post it" in page.text and "My page" in page.text and "#kai" in page.text
    assert api.get(path.rsplit("/", 1)[0] + "/wrongkey").text.count("expired") == 1  # a guessed link does nothing
    assert "Posting now" in api.post(path).text
    assert api.get(f"/companion/pressed/{oid}", headers=tok).json() == {"pressed": True}
    assert "expired" in api.post(path).text  # once only
    ctx.mcp.host = "127.0.0.1"  # the bridge only on this computer: no phone link (it couldn't be reached)
    assert companion.go_link(ctx, oid) is None


def test_captions_move_off_faces_and_short_footage_makes_no_clip(env):
    from clippr import pipeline
    from clippr.media import facecam
    size = (960, 540)
    # Two people: the left one in the top panel, the right one in the content under it, face where captions usually go.
    frames = [[(150, 120, 100, 100), (660, 160, 120, 160)] for _ in range(10)]
    stacked = {"layout": "stacked", "cam": [0.05, 0.05, 0.4, 0.6], "zoom": 1.0, "pan_y": 0.5, "video_height": 1.0}
    y = facecam.caption_spot(frames, size, stacked, 16 / 9)
    assert y is not None and y != 70
    lo, hi = (0.4 + (160 / 540) * 0.6) * 100, (0.4 + (320 / 540) * 0.6) * 100  # the lower face, on the finished video
    assert y - facecam.CAPTION_HALF >= hi or y + facecam.CAPTION_HALF <= lo
    # Nothing near the usual place: the captions stay where the page has them.
    assert facecam.caption_spot([[(400, 40, 80, 80)]] * 10, size, {"zoom": 1.0, "pan_y": 0.5, "video_height": 1.0}, 16 / 9) is None
    # A 5-second post can't be stretched to a clip: none is made.
    ctx, c, fake = env
    try:
        ctx.pipeline._produce_clip(Path("x.mp4"), 0, 5.0, Path("w"), title="t", post_title="t", creator_id=None, creator_name="",
                                   dest_info=[], hints=[], retention_days=30, progress=lambda d: None)
        raise AssertionError("a 5 s clip was made")
    except pipeline.TooShort as e:
        assert "at least 20 s" in str(e)


def test_your_approval_overrides_the_screener_but_never_the_safety_check(ctx, tmp_path):
    from clippr import posting
    ids = _clip(ctx, tmp_path, n=2)
    with ctx.db.session() as s:
        outs = [s.scalars(select(ClipOutput).where(ClipOutput.clip_id == cid)).one() for cid in ids]
        for o in outs:
            o.review = "pending"
        held, bad = (s.get(Clip, cid) for cid in ids)
        held.grade, held.safety = {"score": 20, "screen": {"pass": False, "reasons": ["no payoff"]}}, {"status": "pass"}
        bad.grade, bad.safety = {"score": 90, "screen": {"pass": True}}, {"status": "fail", "flags": [{"level": "fail", "reason": "nudity"}]}
        s.flush()
        try:
            posting.approve(s, outs[0].id, "muse", watched=True)
            raise AssertionError("Muse got past the screener")
        except posting.PostingError as e:
            assert "screener" in str(e)
        assert posting.approve(s, outs[0].id, "you", watched=True).review == "approved"
        try:
            posting.approve(s, outs[1].id, "you", watched=True)
            raise AssertionError("a quarantined clip was approved")
        except posting.PostingError as e:
            assert "Quarantined" in str(e)


def test_after_100_of_your_reviews_vyral_approves_what_you_would_have(ctx, tmp_path):
    from clippr import posting
    ids = _clip(ctx, tmp_path, n=3)
    with ctx.db.session() as s:
        outs = [s.scalars(select(ClipOutput).where(ClipOutput.clip_id == cid)).one() for cid in ids]
        mine, good, low = (s.get(Clip, cid) for cid in ids)
        for c, score in ((mine, 70), (good, 80), (low, 40)):
            c.grade, c.safety = {"score": score, "screen": {"pass": True}}, {"status": "pass"}
        outs[0].reviewed_by = "you"
        for o in outs[1:]:
            o.review, o.quality = "pending", {"status": "pass"}
    assert posting.auto_review(ctx) == {"waiting": "1 of 100 reviews"}
    with ctx.db.session() as s:
        for i in range(99):
            s.add(ClipOutput(clip_id=ids[0], platform="tiktok", status="expired", review="rejected", reviewed_by="you"))
    assert posting.auto_review(ctx) == {"approved": 1, "bar": 70}  # the 40 is under what you approve
    with ctx.db.session() as s:
        assert [s.get(ClipOutput, o.id).reviewed_by for o in outs[1:]] == ["vyral", ""]


def test_clips_that_fail_the_screener_after_the_redo_are_deleted_unless_posted(ctx, tmp_path):
    ids = _clip(ctx, tmp_path, n=2)
    with ctx.db.session() as s:
        s.scalars(select(ClipOutput).where(ClipOutput.clip_id == ids[1])).one().post_url = "https://www.tiktok.com/@mypage/video/2"
    assert ctx.pipeline._delete_unposted(ids, "clips.screened_out") == 1
    with ctx.db.session() as s:
        assert s.get(Clip, ids[0]) is None and s.get(Clip, ids[1]) is not None
    assert not (tmp_path / "c0").exists() and (tmp_path / "c1").exists()

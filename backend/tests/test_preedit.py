"""The viral pre-edit: headline, length, opening on sound, and the headline box in the video."""
import numpy as np

from clippr.media.ffmpeg import ffmpeg_exe

from clippr import preedit
from clippr.media import overlay
from clippr.media.overlay import Word
from clippr.schemas import ClipEdit, OverlaySettings


def _w(text, start=0.0, gap=0.35):
    out, t = [], start
    for tok in text.split():
        out.append(Word(t, t + 0.3, tok))
        t += gap
    return out


def test_titles_quote_the_best_line_or_sum_up_the_moment():
    from clippr import titles
    # A striking line near the big moment wins, word for word, in quotes, with an emoji.
    words = _w("so we were just driving around.") + _w("NO WAY HE ACTUALLY DID THAT!", start=6) + _w("anyway let's keep going", start=12)
    t, quote = titles.make_title(words, "Kai", peak=6.5)
    assert quote and t.startswith("\u201cNo way he actually did that") and t.endswith(("💀", "😳", "🔥", "😭"))
    # No good line: a summary that fits the mood, with the streamer's name. Never the source's own title.
    t2, quote2 = titles.make_title(_w("hahaha hahaha lmao") + _w("hahahaha", start=3), "Lacy")
    assert not quote2 and "Lacy" in t2 and t2.endswith("😭")
    t3, _ = titles.make_title(_w("yeah ok so like"), "Jason")
    assert "Jason" in t3
    assert titles.make_title(words, "Kai", 6.5) == (t, quote)  # the same clip gets the same title every time
    assert titles.best_quote(_w("and then he went over there")) is None  # mid-thought, nothing striking


def test_long_clips_are_trimmed_around_the_peak_and_open_on_sound():
    db = np.full(600, -30.0)  # 60 s
    db[:30] = -70             # 3 s of near silence
    db[450:470] = -5          # the moment, at 45 s
    words = [Word(t, t + 0.3, "word.") for t in np.arange(3.2, 58, 0.5)]
    a, b = preedit.best_window(db, words, 60.0)
    assert a < 45 < b and 45 + 3 <= b and preedit.SHORTEST <= b - a <= preedit.LONGEST
    a, b = preedit.best_window(db, words, 20.0)  # short: kept whole, minus the silent opening
    assert 2.8 <= a <= 3.2 and b == 20.0


def test_apply_adds_the_headline_box_once():
    e = ClipEdit(start=10, end=30).model_dump()
    out = preedit.apply(e, [Word(0.1, 0.4, "hey")], None, "Kai lost it 😭")
    assert out["preedited"] and out["hide_title"] and out["texts"][0]["box"] and out["texts"][0]["text"] == "Kai lost it 😭"
    assert ClipEdit(**out)  # still a valid edit
    assert preedit.apply(out, [], None, "other") == out  # never twice


def test_the_box_is_drawn_as_a_white_box_behind_dark_text():
    ov = OverlaySettings().model_dump()
    ass = overlay.build_ass(1080, 1920, ov, "", [], 20, [{"text": "Kai lost it", "start": 0, "end": 20, "y_percent": 17, "size": 50,
                                                         "color": "#141414", "font": "poppins", "all_caps": False, "outline": 0, "box": True}])
    style = next(x for x in ass.splitlines() if x.startswith("Style: Box,"))
    assert ",3," in style and "&H00FFFFFF" in style  # BorderStyle 3: an opaque box
    assert ",Box,,0,0,0,," in ass and "Kai lost it" in ass


def test_one_sound_on_the_biggest_moment_only():
    db = np.full(300, -30.0)
    assert preedit.auto_sound(db, 0, 30, "") is None  # calm: nothing forced
    db[180:190] = -8  # the moment, at 18 s
    name, at = preedit.auto_sound(db, 0, 30, "")
    assert name == "boom" and 17.5 <= at <= 18.5
    assert preedit.auto_sound(db, 0, 30, "no way bro")[0] == "bass_drop"
    db2 = np.full(300, -30.0); db2[5:15] = -8
    assert preedit.auto_sound(db2, 0, 30, "") is None  # on the opening second: it would cover the hook
    e = preedit.apply(ClipEdit(start=100, end=130).model_dump(), [], db, "Kai lost it 😭", sound=True)
    assert e["sounds"][0]["name"] == "boom" and 117.5 <= e["sounds"][0]["at"] <= 118.5  # in source seconds
    assert ClipEdit(**e).sounds[0].volume == 0.6


def test_quote_headlines_sit_at_the_top_briefly_and_pages_add_their_emoji():
    e = preedit.apply(ClipEdit(start=0, end=20).model_dump(), [], None, "“You're not growing” 😭", quote=True)
    t = e["texts"][0]  # never a line across the middle of the picture for the whole clip
    assert t["headline"] and t["box"] and t["y_percent"] == preedit.HEADLINE_Y and t["end"] <= preedit.TITLE_SECONDS
    assert overlay.with_signature(t["text"], "😭❤️") == "“You're not growing” 😭❤️"
    assert overlay.with_signature("Kai lost it", "🔥") == "Kai lost it 🔥" and overlay.with_signature("Kai 😭", "") == "Kai 😭"


def test_existing_pre_edits_are_upgraded_once():
    old = {**ClipEdit(start=0, end=20).model_dump(), "preedited": True}  # from version 1
    new = preedit.apply(old, [], None, "Kai lost it 😭")
    assert new["preedit_version"] == preedit.VERSION
    assert preedit.apply(new, [], None, "other") == new


def test_every_sound_renders_and_mixes_in_at_its_time(tmp_path):
    from clippr.media import sfx
    from clippr.media.ffmpeg import probe, run
    from clippr.media.render import OutputFormat, render
    for name in sfx.SOUNDS:
        assert probe(sfx.path(name, tmp_path / "s")).duration > 0.1
    src = tmp_path / "src.mp4"
    run(["-f", "lavfi", "-i", "testsrc2=size=320x180:rate=30:duration=4", "-f", "lavfi", "-i", "sine=f=220:d=4,volume=0.02",
         "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", str(src)])
    out = render(src, tmp_path / "o.mp4", OutputFormat(180, 320, 30), duration=4, gaps=[(0.5, 1.0)],
                 sounds=[(sfx.path("boom", tmp_path / "s"), 2.0, 1.0)], use_hardware=False)
    import subprocess
    raw = subprocess.run([ffmpeg_exe(), "-v", "error", "-i", str(out), "-ac", "1", "-ar", "8000", "-f", "s16le", "-"], capture_output=True).stdout
    x = np.frombuffer(raw, np.int16).astype(float) / 32768
    loud = [float(np.sqrt(np.mean(x[i:i + 800] ** 2))) for i in range(0, len(x) - 800, 800)]  # every 0.1 s
    assert 19 <= int(np.argmax(loud)) <= 22  # the boom lands at 2.0 s of the finished clip


def test_sounds_are_listed_and_served(env):
    ctx, c, fake = env
    names = [x["name"] for x in c.get("/api/sounds").json()]
    assert "boom" in names and "whoosh" in names
    r = c.get("/api/media/sounds/boom")
    assert r.status_code == 200 and r.headers["content-type"] == "audio/wav" and len(r.content) > 10000
    assert c.get("/api/media/sounds/../../etc/passwd").status_code in (404, 422)
    assert c.get("/api/media/sounds/nope").status_code == 404


def test_your_own_sounds_upload_list_and_render(env, tmp_path):
    from pathlib import Path
    from clippr.media.ffmpeg import run
    ctx, c, fake = env
    mp3 = tmp_path / "vine boom.mp3"
    run(["-f", "lavfi", "-i", "sine=f=60:d=1", str(mp3)])
    r = c.post("/api/library", files={"file": ("vine boom.mp3", mp3.read_bytes())})
    assert r.status_code == 201 and r.json()["kind"] == "audio", r.text
    lid = r.json()["id"]
    long = tmp_path / "song.mp3"
    run(["-f", "lavfi", "-i", "sine=f=300:d=61", str(long)])
    assert c.post("/api/library", files={"file": ("song.mp3", long.read_bytes())}).status_code == 422  # a song, not a sound
    mine = [x for x in c.get("/api/sounds").json() if x["mine"]]
    assert mine == [{"name": f"lib:{lid}", "label": "vine boom", "use": "your sound", "seconds": mine[0]["seconds"], "mine": True}]
    assert ClipEdit(start=0, end=5, sounds=[{"name": f"lib:{lid}", "at": 1}]).sounds[0].name == f"lib:{lid}"
    assert ctx.pipeline._library_files([lid])[lid][0].exists()
    # Chosen in Settings, it's what lands on the big moment.
    db = np.full(300, -30.0); db[180:190] = -8
    e = preedit.apply(ClipEdit(start=0, end=30).model_dump(), [], db, "x", sound=True, choice=f"lib:{lid}")
    assert e["sounds"][0]["name"] == f"lib:{lid}" and 17.5 <= e["sounds"][0]["at"] <= 18.5
    assert c.put("/api/settings", json={"processing": {"auto_sound": f"lib:{lid}"}}).status_code == 200
    assert c.put("/api/settings", json={"processing": {"auto_sound": "../x"}}).status_code == 422
    Path(ctx.pipeline._library_files([lid])[lid][0]).unlink()
    assert ctx.pipeline._library_files([lid]) == {}  # removed from disk: skipped at render, never a crash


def test_the_best_seconds_become_the_hook():
    db = np.full(300, -30.0)  # 30 s, calm, then the big moment at 20 s
    db[200:240] = -6
    words = [Word(t, t + 0.3, "no way" if 200 <= t * 10 < 240 else "so") for t in np.arange(0.2, 29.5, 0.5)]
    h = preedit.pick_hook(db, words, 0, 30)
    assert h and 19 <= h[0] <= 21 and preedit.HOOK_MIN <= h[1] - h[0] <= preedit.HOOK_MAX + 0.5
    flat = np.full(300, -30.0)
    assert preedit.pick_hook(flat, words, 0, 30) is None  # nothing stands out: no hook
    loud_open = np.full(300, -30.0); loud_open[0:50] = -6
    assert preedit.pick_hook(loud_open, [], 0, 30) is None  # it already opens on its best part
    assert preedit.pick_hook(db, words, 0, 12) is None  # too short to need one
    e = preedit.apply(ClipEdit(start=100, end=130).model_dump(), words, db, "x", hook=True)
    assert e["hook"] and 119 <= e["hook"][0] <= 121  # in source seconds
    assert ClipEdit(**e).hook == e["hook"]


def test_render_plays_the_hook_then_the_clip_from_the_start(tmp_path):
    from clippr.media.ffmpeg import probe, run
    from clippr.media.render import OutputFormat, render
    src = tmp_path / "src.mp4"  # silent for 6 s, then a loud tone from 6 to 8 s
    run(["-f", "lavfi", "-i", "testsrc2=size=320x180:rate=30:duration=10", "-f", "lavfi",
         "-i", "sine=f=440:d=10,volume='if(between(t,6,8),1,0.001)':eval=frame", "-c:v", "libx264", "-preset", "ultrafast",
         "-c:a", "aac", str(src)])
    out = render(src, tmp_path / "o.mp4", OutputFormat(180, 320, 30), duration=10, hook=(6.0, 8.0), use_hardware=False)
    assert abs(probe(out).duration - 12.0) < 0.2  # 2 s of hook + the whole 10 s
    import subprocess
    raw = subprocess.run([ffmpeg_exe(), "-v", "error", "-i", str(out), "-ac", "1", "-ar", "8000", "-f", "s16le", "-"], capture_output=True).stdout
    x = np.frombuffer(raw, np.int16).astype(float) / 32768
    rms = lambda a, b: float(np.sqrt(np.mean(x[int(a * 8000):int(b * 8000)] ** 2)))  # noqa: E731
    assert rms(0.3, 1.7) > 5 * rms(3, 7)  # the loud part plays first...
    assert rms(8.3, 9.7) > 5 * rms(3, 7)  # ...and again in its place (2 s later than in the source)


def test_punch_in_zooms_only_on_the_moment(tmp_path):
    from clippr.media.ffmpeg import run
    from clippr.media.render import OutputFormat, render
    import cv2
    src = tmp_path / "src.mp4"  # a white frame with a black border: zooming in pushes the border off screen
    run(["-f", "lavfi", "-i", "color=c=white:size=320x568:rate=30:duration=4", "-f", "lavfi", "-i", "anullsrc=r=48000:cl=stereo",
         "-vf", "drawbox=x=0:y=0:w=320:h=568:color=black:t=12", "-t", "4", "-c:v", "libx264", "-preset", "ultrafast", "-c:a", "aac", str(src)])
    out = render(src, tmp_path / "o.mp4", OutputFormat(320, 568, 30), duration=4, punch=[(2.0, 3.0)], use_hardware=False)
    def corner(t):
        f = tmp_path / f"f{t}.png"
        run(["-ss", str(t), "-i", str(out), "-frames:v", "1", str(f)])
        return int(cv2.imread(str(f))[3, 3].mean())
    assert corner(1.0) < 60 and corner(2.5) > 200 and corner(3.5) < 60  # border, zoomed past it, border again
    e = preedit.apply(ClipEdit(start=10, end=40).model_dump(), [], np.where((np.arange(300) >= 150) & (np.arange(300) < 160), -5.0, -30.0), "x")
    assert e["punch"] and 24.5 < e["punch"][0] < 25.5



def test_clips_end_once_the_climax_settles():
    db = np.full(300, -30.0)  # 30 s: a reaction at 12 s, then 15 s of calm chatter
    db[120:140] = -6
    a, b = preedit.best_window(db, _w(" ".join(["talk"] * 80), gap=0.37), 30.0)
    assert 14 < b < 22, (a, b)  # ends a little after it settles, not at 30 s


def test_captions_already_in_the_footage_are_found(tmp_path):
    from clippr.media.ffmpeg import run
    from clippr.media.onscreen import has_captions
    bg = "gradients=s=576x1024:speed=0.02:d=12"
    words = ["NO WAY", "HE REALLY", "JUST DID THAT", "BRO WHAT", "ARE YOU SERIOUS", "I CANT", "THAT HAPPENED", "LETS GO"]
    live = ",".join(f"drawtext=text='{w}':fontsize=44:fontcolor=yellow:borderw=4:x=(w-tw)/2:y=h*0.72:enable='between(t,{i*1.5},{i*1.5+1.5})'"
                    for i, w in enumerate(words))
    run(["-f", "lavfi", "-i", bg, "-vf", live, "-c:v", "libx264", "-preset", "ultrafast", str(tmp_path / "live.mp4")])
    run(["-f", "lavfi", "-i", bg, "-vf", "drawtext=text='Lacy could not believe this':fontsize=40:fontcolor=black:box=1:boxcolor=white:x=(w-tw)/2:y=h*0.6",
         "-c:v", "libx264", "-preset", "ultrafast", str(tmp_path / "title.mp4")])
    run(["-f", "lavfi", "-i", bg, "-c:v", "libx264", "-preset", "ultrafast", str(tmp_path / "plain.mp4")])
    assert has_captions(tmp_path / "live.mp4", 0, 12)
    assert not has_captions(tmp_path / "title.mp4", 0, 12)  # a fixed title isn't captions
    assert not has_captions(tmp_path / "plain.mp4", 0, 12)

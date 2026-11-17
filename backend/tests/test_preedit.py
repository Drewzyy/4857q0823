"""The viral pre-edit: headline, length, opening on sound, and the headline box in the video."""
import numpy as np

from clippr import preedit
from clippr.media import overlay
from clippr.media.overlay import Word
from clippr.schemas import ClipEdit, OverlaySettings


def test_headline_uses_the_source_post_and_adds_one_emoji():
    h = preedit.headline("Lacy couldn't believe Dani drank a random person's drink #fyp #lacy", "x", "Lacy")
    assert h.startswith("Lacy couldn't believe Dani drank a random person's drink") and "#" not in h
    assert h.endswith(("😭", "😳", "💀", "😤", "😬"))
    assert preedit.headline("Ron was in shock after Marlon surprised him 😭", "x", "Ron").count("😭") == 1  # keeps its own


def test_headline_falls_back_to_a_quote_of_the_clip_line():
    h, quote = preedit.plan_headline("", "NO WAY HE ACTUALLY DID THAT", "Kai")
    assert quote
    assert h.startswith("“No way he actually did that”") and h.endswith(("😳", "💀"))


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


def test_caption_keeps_the_source_hashtags():
    assert preedit.caption_source("Kai lost it 😭", "lol #kaicenat #fyp") == "Kai lost it 😭 #kaicenat #fyp"
    assert preedit.caption_source("", "lol #kai") == "lol #kai"


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


def test_quote_headlines_are_white_text_and_pages_add_their_emoji():
    e = preedit.apply(ClipEdit(start=0, end=20).model_dump(), [], None, "“You're not growing” 😭", quote=True)
    t = e["texts"][0]
    assert t["headline"] and not t.get("box") and t["color"] == "#FFFFFF" and t["y_percent"] == preedit.QUOTE_Y
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
    raw = subprocess.run(["ffmpeg", "-v", "error", "-i", str(out), "-ac", "1", "-ar", "8000", "-f", "s16le", "-"], capture_output=True).stdout
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

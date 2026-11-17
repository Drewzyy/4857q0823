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


def test_headline_falls_back_to_the_clip_line_with_the_streamers_name():
    h = preedit.headline("", "NO WAY HE ACTUALLY DID THAT", "Kai")
    assert h.startswith("Kai: “No way he actually did that") and h.endswith(("😳", "💀"))


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

"""Color emoji in titles and on-video text."""
from clippr.media import emoji, overlay
from clippr.schemas import OverlaySettings

PNG = b"\x89PNG\r\n\x1a\n" + b"\0" * 32


def test_emoji_are_split_whole():
    assert emoji.split("go 👨‍👩‍👧 now 🇺🇸!👍🏽") == ["go ", "👨‍👩‍👧", " now ", "🇺🇸", "!", "👍🏽"]
    assert not emoji.has_emoji("plain text #fyp")


def test_emoji_get_gaps_and_positions_inside_the_frame(tmp_path):
    font = overlay.FONT_DIR / overlay.FONTS["montserrat"][0]
    ass, placed = emoji.layout("HE DID NOT 😂 JUST DO THAT 🔥", font, 80, 940, 540, 300)
    assert ass.startswith("{\\q2}") and ass.count("\\fscx") == 4  # a gap opened and closed per emoji
    assert [p.emoji for p in placed] == ["😂", "🔥"]
    assert all(70 <= p.x <= 1010 and abs(p.size - 80 * emoji.EMOJI_SCALE) < 0.01 for p in placed)
    assert placed[0].x < placed[1].x or placed[0].y < placed[1].y  # in reading order


def test_titles_keep_emoji_when_the_picture_is_available_and_drop_it_otherwise(tmp_path):
    (tmp_path / "1f602.png").write_bytes(PNG)
    (tmp_path / "1f525.missing").touch()  # known not to exist: skipped without going online
    ov = OverlaySettings().model_dump()
    out: list = []
    ass = overlay.build_ass(1080, 1920, ov, "crazy 😂 play 🔥", [], 5, emoji_cache=tmp_path, emoji_out=out)
    assert [pl.emoji for _, _, pl, _ in out] == ["😂"]
    assert "🔥" not in ass and "😂" not in ass  # the renderer never sees an emoji character
    # Without an emoji folder (old behaviour), emoji are simply removed.
    assert "😂" not in overlay.build_ass(1080, 1920, ov, "crazy 😂", [], 5)

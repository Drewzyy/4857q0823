"""The caption maker must turn messy speech-model output into clean, readable captions."""
from clippr.media.overlay import Word, apply_text_edit, build_ass, chunk_words, clean_words, max_chars
from clippr.schemas import OverlaySettings


def W(*items):
    return [Word(s, e, t) for s, e, t in items]


def texts(ws):
    return [w.text for w in ws]


def test_repeated_phrase_glitch_is_collapsed():
    raw = W(*[(i * 0.4, i * 0.4 + 0.3, t) for i, t in enumerate("let's go let's go let's go let's go let's go".split())])
    out = clean_words(raw, 10)
    assert texts(out) == ["let's", "go", "let's", "go"]


def test_single_word_stutter_loop_is_collapsed():
    raw = W(*[(i * 0.3, i * 0.3 + 0.2, "no") for i in range(8)])
    assert texts(clean_words(raw, 10)) == ["no", "no"]


def test_invented_filler_over_silence_is_dropped():
    assert clean_words(W((0.5, 1.0, "Thanks"), (1.0, 1.2, "for"), (1.2, 1.6, "watching!")), 5) == []
    assert clean_words(W((0.5, 1.0, "♪")), 5) == []


def test_punctuation_tokens_merge_and_overlaps_are_fixed():
    raw = W((0.0, 0.5, "wait"), (0.5, 0.52, "..."), (0.4, 0.9, "what"), (0.85, 0.85, "?"), (3.0, 3.0, "huh"))
    out = clean_words(raw, 10)
    assert texts(out) == ["wait...", "what?", "huh"]
    for a, b in zip(out, out[1:]):
        assert a.end <= b.start + 1e-9  # never overlapping
    assert all(w.end - w.start >= 0.05 for w in out)  # zero-length words get a visible moment


def test_words_outside_the_clip_are_clamped_or_dropped():
    out = clean_words(W((-0.7, -0.1, "cut"), (-0.2, 0.3, "off"), (4.8, 5.4, "end"), (5.2, 5.6, "after")), 5.0)
    assert texts(out) == ["off", "end"] and out[0].start == 0 and out[-1].end <= 5.0


def test_captions_fit_on_one_line_and_never_flicker():
    style = OverlaySettings().captions.model_dump()
    limit = max_chars(style, 1080)
    assert 12 <= limit <= 20  # Montserrat Black, size 88, ALL CAPS on 1080 wide
    raw = W(*[(i * 0.35, i * 0.35 + 0.3, t) for i, t in enumerate("unbelievable absolutely incredible what just happened bro".split())])
    chunks = chunk_words(raw, 3, limit)
    assert all(len(c.text) <= limit or " " not in c.text for c in chunks)
    for a, b in zip(chunks, chunks[1:]):
        assert a.end <= b.start + 1e-9 and (b.start - a.end) < 0.35 or a.end == b.start  # held through short gaps
    assert all(c.end - c.start >= 0.3 for c in chunks)


def test_sentence_ends_and_pauses_start_new_captions():
    raw = W((0, 0.3, "no."), (0.35, 0.6, "way"), (2.0, 2.3, "bro"))
    assert texts(chunk_words(raw, 4)) == ["no.", "way", "bro"]


def test_smaller_fonts_fit_more_words():
    s = OverlaySettings().captions.model_dump()
    assert max_chars({**s, "font": "bebas"}, 1080) > max_chars(s, 1080)
    assert max_chars({**s, "size": 60}, 1080) > max_chars(s, 1080)


def test_default_title_white_captions_yellow():
    o = OverlaySettings()
    assert o.title.color == "#FFFFFF" and o.captions.color == "#FFE500" and o.title.all_caps and o.captions.all_caps
    ass = build_ass(1080, 1920, o.model_dump(), "title", W((0, 1, "hi")), 3)
    assert "Style: Title,Montserrat Black,76,&H00FFFFFF" in ass and "Style: Caption,Montserrat Black,88,&H0000E5FF" in ass


def test_text_edit_keeps_timing():
    words = W((0, 0.4, "no"), (0.4, 0.8, "way"), (0.8, 1.2, "he"), (1.2, 1.6, "did"))
    out = apply_text_edit(words, "no way she did it")
    assert texts(out) == ["no", "way", "she", "did", "it"]
    assert out[2].start == 0.8 and out[3].start == 1.2

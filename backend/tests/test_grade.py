"""The clip grader: strong clips score high, weak ones low, and every part explains itself."""
from datetime import datetime, timedelta, timezone

import numpy as np

from clippr.grade import grade


def _db(length, base=-30.0, hook=True, peaks=3, end_strong=True):
    db = np.full(int(length * 10), base) + np.random.default_rng(1).normal(0, 1.5, int(length * 10))
    if hook:
        db[:20] = base + 12
    for i in range(peaks):
        k = int((i + 1) * len(db) / (peaks + 1))
        db[k:k + 8] = base + 16
    if end_strong:
        db[-25:-15] = base + 14
    return db


def test_a_strong_clip_is_s_tier():
    words = [(i * 0.35, i * 0.35 + 0.3, "w") for i in range(90)]
    g = grade(db=_db(32), words=words, length=32, has_captions=True, has_title=True, views=2_000_000, likes=300_000,
              shares=40_000, posted_at=datetime.now(timezone.utc) - timedelta(hours=10))
    assert g.tier == "S" and g.score >= 85, g
    assert {p["name"] for p in g.parts} >= {"Hook in the first 3 seconds", "Length", "Proof people care"}


def test_a_slow_quiet_long_clip_is_low_and_says_why():
    db = _db(150, hook=False, peaks=0, end_strong=False)
    db[: 30] = -70  # silent opening
    g = grade(db=db, words=[(40, 41, "hi")], length=150, has_captions=False, has_title=False)
    assert g.tier in ("C", "D"), g
    assert len(g.tips) == 3 and "closer to the action" in g.tips[0]  # the biggest fix (the hook) comes first
    assert next(p for p in g.parts if p["name"] == "Captions and title")["points"] == 0


def test_stream_clip_views_count_as_proof():
    common = dict(db=_db(25), words=[(i * 0.4, i * 0.4 + 0.3, "w") for i in range(60)], length=25, has_captions=True, has_title=True)
    hot = grade(**common, views=2500, stream_clip=True)
    cold = grade(**common, views=3, stream_clip=True)
    assert hot.score > cold.score + 15


def test_emotion_and_a_curious_opening_score_higher():
    db = _db(30)
    plain = grade(db=db, words=[(0.1, 0.4, "so"), (0.5, 0.8, "today"), (0.9, 1.2, "we"), (10, 10.3, "okay")], length=30, has_captions=True, has_title=True)
    hyped = grade(db=db, words=[(0.1, 0.4, "wait"), (0.5, 0.8, "watch"), (0.9, 1.2, "this"), (10, 10.3, "no"), (10.3, 10.6, "way"),
                                (11, 11.3, "oh"), (11.3, 11.6, "no"), (12, 12.3, "run")], length=30, has_captions=True, has_title=True, lift=0.3)
    part = lambda g, n: next(p for p in g.parts if p["name"] == n)["points"]  # noqa: E731
    assert part(hyped, "Hook in the first 3 seconds") > part(plain, "Hook in the first 3 seconds")
    assert part(hyped, "Energy and emotion") > part(plain, "Energy and emotion")
    assert "awe" in next(p for p in hyped.parts if p["name"] == "Energy and emotion")["note"]


def test_slow_intros_and_long_titles_lose_points():
    db = _db(30)
    quick = [(0.1, 0.4, "no"), (0.5, 0.8, "way"), (0.9, 1.2, "he"), (1.3, 1.6, "did")]
    slow = [(0.1, 0.4, "hey"), (0.5, 0.8, "guys"), (0.9, 1.2, "welcome"), (1.3, 1.6, "back")]
    part = lambda g, n: next(p for p in g.parts if p["name"] == n)  # noqa: E731
    a = grade(db=db, words=quick, length=30, has_captions=True, has_title=True, title="He jumped the gap")
    b = grade(db=db, words=slow, length=30, has_captions=True, has_title=True,
              title="So this is what happened when we finally tried to do the craziest heist in the game")
    assert part(a, "Hook in the first 3 seconds")["points"] > part(b, "Hook in the first 3 seconds")["points"]
    assert "slow intro" in part(b, "Hook in the first 3 seconds")["note"]
    assert part(a, "Captions and title")["points"] > part(b, "Captions and title")["points"]
    assert any("3 to 7 words" in t for t in b.tips) or part(b, "Captions and title")["points"] < 5

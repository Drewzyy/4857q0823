"""Dead air: stretches of a clip where nothing is said or heard. They're cut out so the clip keeps moving.

Found with FFmpeg's silence detector on the clip's audio. A little sound is kept on each side of every cut so
words aren't clipped, short pauses are left alone (they're natural), and a cut never removes so much that the
clip gets too short. Gaps are stored in source-file seconds, so moving the trim in the editor keeps them right.
"""
from __future__ import annotations

import re
from pathlib import Path

from .ffmpeg import FFmpegError, run

NOISE_DB = -38      # quieter than this counts as silence
MIN_SILENCE = 1.0   # only pauses at least this long are cut
PAD = 0.25          # sound kept on each side of a cut
MIN_LEFT = 3.0      # never cut a clip below this many seconds

_START = re.compile(r"silence_start: (-?[\d.]+)")
_END = re.compile(r"silence_end: (-?[\d.]+)")


def detect(src: Path, start: float, dur: float) -> list[list[float]]:
    """Dead-air gaps to cut, as [from, to] in source seconds."""
    try:
        err = run(["-ss", f"{start:.3f}", "-t", f"{dur:.3f}", "-i", str(src), "-vn",
                   "-af", f"silencedetect=noise={NOISE_DB}dB:d={MIN_SILENCE}", "-f", "null", "-"], timeout=300)
    except FFmpegError:
        return []
    starts = [float(x) for x in _START.findall(err)]
    ends = [float(x) for x in _END.findall(err)]
    ends += [dur] * (len(starts) - len(ends))  # silent to the end
    gaps, removed = [], 0.0
    for a, b in zip(starts, ends):
        a, b = max(a, 0) + (PAD if a > 0 else 0), min(b, dur) - (PAD if b < dur else 0)
        if b - a < 0.4 or dur - removed - (b - a) < MIN_LEFT:
            continue
        gaps.append([round(start + a, 3), round(start + b, 3)])
        removed += b - a
    return gaps


def relative(gaps: list[list[float]] | None, start: float, dur: float) -> list[tuple[float, float]]:
    """Gaps inside the cut, as seconds from its start, sorted and with overlaps merged (dead air and the user's
    own cuts can overlap)."""
    out: list[tuple[float, float]] = []
    for a, b in sorted((max(a - start, 0.0), min(b - start, dur)) for a, b in gaps or []):
        if b - a <= 0.05:
            continue
        if out and a <= out[-1][1]:
            out[-1] = (out[-1][0], max(out[-1][1], b))
        else:
            out.append((a, b))
    return out


def removed_before(t: float, rel: list[tuple[float, float]]) -> float:
    return sum(min(b, t) - a for a, b in rel if a < t)


def inside(t: float, rel: list[tuple[float, float]]) -> bool:
    return any(a <= t < b for a, b in rel)


# Fillers that are never part of what's being said. "like" and "you know" are left alone: too often real words.
FILLER = re.compile(r"^(u+h+m*|u+m+|e+r+m+|e+h+|h+m+|m+h*m+|a+h+m*)[.,!?…]*$", re.I)
PAUSE = 0.7          # a gap between words longer than this is tightened
PAUSE_LEFT = 0.25    # how much of a tightened pause stays, so speech still breathes
WORD_PAD = 0.04


def speech_gaps(words: list, start: float, dur: float, db=None, step: float = 0.1) -> list[list[float]]:
    """Filler words ("um", "uh") and long pauses between words, as [from, to] in source seconds. words are timed
    from `start` (they need .start, .end, .text). A pause is only tightened when it is also quiet (`db`, the
    clip's loudness every `step` s): on a stream the gap between words is often the scream, the laugh or the
    big play, and that must stay."""
    if not words:
        return []
    talk = None
    if db is not None and len(db):
        import numpy as np
        spoken = [db[int(w.start / step):max(int(w.start / step) + 1, int(w.end / step))] for w in words]
        spoken = [x for x in spoken if len(x)]
        talk = float(np.median(np.concatenate(spoken))) if spoken else None

    def quiet(a: float, b: float) -> bool:
        if talk is None:
            return False  # can't tell what's in the gap: keep it
        seg = db[round(a / step) + 1:round(b / step) - 1]  # inside the pause, clear of the words' edges
        return len(seg) > 0 and float(seg.max()) < talk - 8

    gaps: list[list[float]] = []
    removed = 0.0

    def cut(a: float, b: float) -> None:
        nonlocal removed
        if b - a >= 0.12 and dur - removed - (b - a) >= MIN_LEFT:
            gaps.append([round(start + a, 3), round(start + b, 3)])
            removed += b - a

    spoken = [w for w in words if not FILLER.match(w.text.strip())]
    for w in words:
        if FILLER.match(w.text.strip()):
            cut(w.start + WORD_PAD, w.end - WORD_PAD)
    for prev, nxt in zip(spoken, spoken[1:]):
        a, b = prev.end + PAUSE_LEFT / 2, nxt.start - PAUSE_LEFT / 2
        if nxt.start - prev.end > PAUSE and quiet(prev.end, nxt.start):
            cut(a, b)
    return sorted(gaps)

"""Clip grader: how likely a clip is to do well as a TikTok / Short / Reel, from S down to D, with the reasons.

What the scoring is based on (the platforms don't publish their ranking, so this follows what creators and
short-form analytics consistently report):
- Proof people care: the moment was already clipped and watched, or the post it came from is getting views,
  likes and shares fast. This is the strongest predictor, and the only one measured on real viewers.
- The hook: most viewers who leave do so in the first 3 seconds, so the clip must open with speech or a loud,
  high-energy moment, not silence or a slow build.
- Energy: reaction peaks (shouting, laughing, explosions) well above the clip's normal level.
- Pacing: steady talking and little dead air keep people watching to the end.
- Length: about 15 to 60 seconds finishes most often; very short clips lack payoff and long ones lose viewers.
- Captions and a title: most people watch muted, and the title tells them why to stay.
- Payoff: the clip ends on or near its biggest moment instead of trailing off.

The grade is a prediction, never a promise: S means every signal Vyral can measure is strong, not that a clip
is guaranteed to go viral. Scores are recomputed when a clip is edited.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from .media.ffmpeg import FFmpegError, ffmpeg_exe

TIERS = (("S", 85), ("A", 70), ("B", 55), ("C", 40), ("D", 0))
STEP = 0.1  # loudness is measured every 100 ms


@dataclass
class Grade:
    score: int
    tier: str
    parts: list[dict] = field(default_factory=list)  # {name, points, max, note}
    tips: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {"score": self.score, "tier": self.tier, "parts": self.parts, "tips": self.tips}


def loudness(path: Path, start: float, dur: float, gaps: list[tuple[float, float]] = ()) -> np.ndarray:
    """Loudness (dB) every 100 ms of the finished clip: the cut's audio with removed stretches left out."""
    import subprocess

    sr = 8000
    try:
        raw = subprocess.run([ffmpeg_exe(), "-v", "error", "-ss", f"{start:.3f}", "-t", f"{dur:.3f}", "-i", str(path),
                              "-vn", "-ac", "1", "-ar", str(sr), "-f", "s16le", "-"], capture_output=True, timeout=120, check=True).stdout
    except (subprocess.SubprocessError, OSError) as e:
        raise FFmpegError(f"couldn't read the clip's audio ({type(e).__name__})")
    x = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768
    if gaps:
        keep = np.ones(len(x), bool)
        for a, b in gaps:
            keep[int(a * sr):int(b * sr)] = False
        x = x[keep]
    hop = int(sr * STEP)
    n = len(x) // hop
    if n == 0:
        return np.zeros(0)
    frames = x[: n * hop].reshape(n, hop)
    return 20 * np.log10(np.sqrt((frames ** 2).mean(axis=1)) + 1e-6)


def _tier(score: int) -> str:
    return next(t for t, floor in TIERS if score >= floor)


def _proof(views: int | None, likes: int | None, shares: int | None, posted_at: datetime | None, stream_clip: bool) -> tuple[float, str]:
    """0..1 for how much real viewers already care, from the post or stream clip it came from."""
    if not views:
        return 0.3, "No view numbers for the original yet, so this part is neutral."
    hours = max(1.0, (datetime.now(timezone.utc) - posted_at).total_seconds() / 3600) if posted_at else 24.0
    per_hour = views / hours
    if stream_clip:  # a stream clip with a few hundred views in a day is a lot
        level = min(1.0, math.log10(1 + views) / math.log10(1 + 3000))
        return level, f"Viewers clipped it and it has {views:,} views on the stream platform."
    reach = min(1.0, math.log10(1 + views) / 6)  # 1M views = full marks
    speed = min(1.0, math.log10(1 + per_hour) / 4.5)  # ~30k views an hour = full marks
    engaged = 0.0
    if likes:
        engaged = min(1.0, (likes + 3 * (shares or 0)) / max(views, 1) / 0.12)  # ~12% weighted engagement is excellent
    level = 0.4 * reach + 0.35 * speed + 0.25 * engaged
    return level, f"The original has {views:,} views ({per_hour:,.0f} an hour)" + (f" and {likes:,} likes." if likes else ".")


def grade(*, db: np.ndarray, words: list[tuple[float, float, str]], length: float, has_captions: bool, has_title: bool,
          views: int | None = None, likes: int | None = None, shares: int | None = None, posted_at: datetime | None = None,
          stream_clip: bool = False) -> Grade:
    """db: loudness every 100 ms of the finished clip. words: (start, end, text) in finished-clip seconds."""
    parts, tips = [], []

    def add(name: str, frac: float, top: int, note: str, tip: str | None = None) -> None:
        pts = round(max(0.0, min(1.0, frac)) * top)
        parts.append({"name": name, "points": pts, "max": top, "note": note})
        if tip and pts < top * 0.6:
            tips.append((top - pts, tip))

    proof, note = _proof(views, likes, shares, posted_at, stream_clip)
    add("Proof people care", proof, 30, note)

    active = db[db > -60] if len(db) else db
    base = float(np.median(active)) if len(active) else -60.0
    peak = float(np.percentile(active, 97)) if len(active) else -60.0
    first3 = db[: int(3 / STEP)]
    early_words = sum(1 for s, _, _ in words if s < 2.0)
    early_energy = float(np.percentile(first3, 90)) if len(first3) else -60.0
    hook = 0.5 * min(1.0, early_words / 3) + 0.5 * min(1.0, max(0.0, early_energy - base + 3) / 9)
    add("Hook in the first 3 seconds", hook, 20,
        f"{early_words} word{'' if early_words == 1 else 's'} in the first 2 s; the opening is {early_energy - base:+.0f} dB against the clip's usual level.",
        "Start the clip closer to the action: cut the lead-in so it opens on talking or the loud moment (drag the start in the editor).")

    spikes = int(((db[1:] > base + 10) & (db[:-1] <= base + 10)).sum()) if len(db) > 1 else 0
    energy = 0.6 * min(1.0, max(0.0, peak - base) / 15) + 0.4 * min(1.0, spikes / max(1.0, length / 10))
    add("Energy and reactions", energy, 15, f"Biggest moments hit {peak - base:.0f} dB above normal, {spikes} spike{'' if spikes == 1 else 's'}.",
        "This one is calm. Clips with a clear reaction (shouting, laughing, a big play) do much better.")

    rate = len(words) / max(length, 1)
    silent = float((db < base - 15).mean()) if len(db) else 1.0
    pacing = 0.6 * (1 - min(1.0, abs(rate - 2.6) / 2.6)) + 0.4 * (1 - min(1.0, silent / 0.25))
    add("Pacing", pacing, 10, f"{rate:.1f} words a second, {silent * 100:.0f}% quiet.",
        "There are quiet stretches. Turn on Dead air > Cut out, or cut the slow part.")

    if 15 <= length <= 60:
        fit = 1.0
    elif length < 15:
        fit = max(0.0, (length - 5) / 10)
    else:
        fit = max(0.0, 1 - (length - 60) / 60)
    add("Length", fit, 10, f"{length:.0f} s long; 15 to 60 s is the sweet spot.",
        "Trim it toward 15 to 60 seconds." if length > 60 else "It's very short; give the moment a little setup.")

    add("Captions and title", (0.6 if has_captions else 0) + (0.4 if has_title else 0), 10,
        ("Captions on" if has_captions else "No captions") + (", title on." if has_title else ", no title."),
        "Turn captions on: most people scroll with the sound off.")

    tail = db[int(len(db) * 0.75):] if len(db) else db
    payoff = min(1.0, max(0.0, (float(np.percentile(tail, 90)) - base + 2) / 8)) if len(tail) else 0.0
    add("Ends on the payoff", payoff, 5, "The last quarter is " + ("as strong as the rest." if payoff >= 0.6 else "quieter than the rest."),
        "End the clip right after the big moment instead of letting it trail off.")

    score = sum(p["points"] for p in parts)
    # The three fixes worth the most points first.
    return Grade(score, _tier(score), parts, [t for _, t in sorted(tips, key=lambda x: -x[0])[:3]])

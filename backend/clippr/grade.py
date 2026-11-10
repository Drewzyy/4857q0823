"""Clip grader: how likely a clip is to do well as a TikTok / Short / Reel, from S down to D, with the reasons.

What the scoring is based on (the platforms don't publish their ranking, so this follows what creators and
short-form analytics consistently report):
- Proof people care: the moment was already clipped and watched, or the post it came from is getting views,
  likes and shares fast. This is the strongest predictor, and the only one measured on real viewers.
- The hook: most viewers who leave do so in the first 3 seconds, so the clip must open with speech or a loud,
  high-energy moment, not silence or a slow build.
- Energy and emotion: reaction peaks well above the clip's normal level, a voice pitched up (how sports and esports
  highlight research spots excitement), and high-arousal emotion in the words: awe, amusement, anger, anxiety
  (Berger & Milkman found these drive sharing, whatever their sign).
- The hook also counts a question or "watch this" in the opening: a curiosity gap viewers stay to close.
- Pacing: steady talking and little dead air keep people watching to the end.
- Length: 20 to 45 seconds for stream and gaming clips; shorter lacks setup, longer loses viewers.
- Loops: when the last frame flows back into the first, the clip gets replayed, which platforms count as a
  rewatch (YouTube Shorts and TikTok creator guidance).
- Visual pace: the first frame is already moving and the picture keeps changing; the most-viewed clips are
  the fastest, not the best looking.
- Captions and a title: table stakes now (most people watch muted), so they count, but less.
- Payoff: the clip ends on or near its biggest moment instead of trailing off.

The grade is a prediction, never a promise: S means every signal Vyral can measure is strong, not that a clip
is guaranteed to go viral. Scores are recomputed when a clip is edited.
"""
from __future__ import annotations

import math
import re
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
    hop = int(sr * STEP)
    if start == 0 and not gaps and dur > 600:
        # A whole long video (long-form): read it in 2-minute pieces so hours of audio never sit in memory at once.
        from .media.ffmpeg import decode_audio_chunks
        out = []
        for chunk in decode_audio_chunks(path, sr):  # 120 s pieces split evenly into 100 ms steps
            n = len(chunk) // hop
            if n:
                out.append(20 * np.log10(np.sqrt((chunk[: n * hop].reshape(n, hop) ** 2).mean(axis=1)) + 1e-6))
        return np.concatenate(out) if out else np.zeros(0)
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
    n = len(x) // hop
    if n == 0:
        return np.zeros(0)
    frames = x[: n * hop].reshape(n, hop)
    return 20 * np.log10(np.sqrt((frames ** 2).mean(axis=1)) + 1e-6)


# High-arousal emotions get shared most, whatever their sign (Berger & Milkman, ~7,000 NYT articles): awe,
# amusement, anger and anxiety. These are the words people say when they feel them.
AROUSAL = {
    "awe": re.compile(r"\b(no way|holy|insane|crazy|unbelievable|incredible|oh my (god|gosh)|what the|how did|clean|cracked|goated|let'?s go+)\b", re.I),
    "amusement": re.compile(r"\b(ha(ha)+|lmao|lol|i'?m dying|bro+|dude|you'?re (so )?funny|stop it)\b", re.I),
    "anger": re.compile(r"\b(are you (kidding|serious)|what are you doing|trash|rigged|bs|come on|why would|hell no|shut up)\b", re.I),
    "anxiety": re.compile(r"\b(oh no|run+|help|he'?s (right )?(here|behind)|we'?re dead|i'?m dead|hurry|watch out|go go)\b", re.I),
}
# Opening on a question or a "watch this" opens a curiosity gap the viewer stays to close.
CURIOUS = re.compile(r"\?|\b(watch|wait|look at|guess|you won'?t believe|did you see|how|why|what if|bet)\b", re.I)


def arousal(text: str) -> list[str]:
    """The high-arousal emotions this speech shows."""
    return [name for name, rx in AROUSAL.items() if rx.search(text)]


def voice_lift(path: Path, start: float, dur: float) -> float | None:
    """How much of the talking is pitched up (yelling, hype): the share of voiced moments at least 25% above the
    speaker's usual pitch. Raised pitch with loudness is what sports and esports highlight research uses for
    excitement. None if there's too little voice to judge."""
    import subprocess

    sr = 8000
    try:
        raw = subprocess.run([ffmpeg_exe(), "-v", "error", "-ss", f"{start:.3f}", "-t", f"{dur:.3f}", "-i", str(path),
                              "-vn", "-ac", "1", "-ar", str(sr), "-f", "s16le", "-"], capture_output=True, timeout=120, check=True).stdout
    except (subprocess.SubprocessError, OSError):
        return None
    x = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32768
    return pitch_lift(x, sr)


def pitch_lift(x: np.ndarray, sr: int) -> float | None:
    n = int(sr * 0.04)  # 40 ms frames
    frames = x[: len(x) // n * n].reshape(-1, n)
    if len(frames) < 25:
        return None
    frames = frames - frames.mean(axis=1, keepdims=True)
    loud = np.sqrt((frames ** 2).mean(axis=1)) > 0.01
    spec = np.fft.rfft(frames * np.hanning(n), 2 * n)
    ac = np.fft.irfft(np.abs(spec) ** 2)[:, :n]
    lo, hi = int(sr / 400), int(sr / 75)  # voices sit between 75 and 400 Hz
    lag = lo + ac[:, lo:hi].argmax(axis=1)
    voiced = loud & (ac[np.arange(len(ac)), lag] > 0.45 * ac[:, 0])
    if voiced.sum() < 15:
        return None
    f0 = sr / lag[voiced]
    return float((f0 > 1.25 * np.median(f0)).mean())


def picture(path: Path, start: float, dur: float) -> tuple[np.ndarray | None, float | None]:
    """From tiny grey frames twice a second (cheap): how much the picture changes between frames (0 still .. 1
    all new), and how closely the last frame matches the first (1 = a seamless loop)."""
    import subprocess

    w, h = 64, 36
    try:
        raw = subprocess.run([ffmpeg_exe(), "-v", "error", "-ss", f"{start:.3f}", "-t", f"{dur:.3f}", "-i", str(path), "-an",
                              "-vf", f"fps=2,scale={w}:{h},format=gray", "-f", "rawvideo", "-"], capture_output=True, timeout=120, check=True).stdout
    except (subprocess.SubprocessError, OSError):
        return None, None
    frames = np.frombuffer(raw, dtype=np.uint8)[: len(raw) // (w * h) * w * h].reshape(-1, h, w).astype(np.float32) / 255
    if len(frames) < 2:
        return None, None
    loop = 1 - min(1.0, float(np.abs(frames[-1] - frames[0]).mean()) / 0.15)
    return np.abs(np.diff(frames, axis=0)).mean(axis=(1, 2)), loop


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
          stream_clip: bool = False, motion: np.ndarray | None = None, lift: float | None = None,
          loop: float | None = None) -> Grade:
    """db: loudness every 100 ms of the finished clip. words: (start, end, text) in finished-clip seconds.
    motion: how much the picture changes, 0..1, every 0.5 s of the finished clip (None if it couldn't be read)."""
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
    early_words = sum(1 for st, _, _ in words if st < 2.0)
    opening = " ".join(w for st, _, w in words if st < 3.0)
    curious = bool(CURIOUS.search(opening))
    early_energy = float(np.percentile(first3, 90)) if len(first3) else -60.0
    hook = (0.4 * min(1.0, early_words / 3) + 0.4 * min(1.0, max(0.0, early_energy - base + 3) / 9)
            + 0.2 * (1.0 if curious else 0.0))
    add("Hook in the first 3 seconds", hook, 20,
        f"{early_words} word{'' if early_words == 1 else 's'} in the first 2 s; the opening is {early_energy - base:+.0f} dB against the clip's usual level"
        + ("; it opens a question." if curious else "."),
        "Start the clip closer to the action: cut the lead-in so it opens on talking or the loud moment (drag the start in the editor).")

    # Energy: loud peaks, a voice pitched up, and high-arousal emotion in what's said (all three predict sharing).
    spikes = int(((db[1:] > base + 10) & (db[:-1] <= base + 10)).sum()) if len(db) > 1 else 0
    feels = arousal(" ".join(w for _, _, w in words))
    loud = 0.6 * min(1.0, max(0.0, peak - base) / 15) + 0.4 * min(1.0, spikes / max(1.0, length / 10))
    voice = min(1.0, lift / 0.25) if lift is not None else 0.5
    energy = 0.55 * loud + 0.2 * voice + 0.25 * min(1.0, len(feels) / 2)
    add("Energy and emotion", energy, 15,
        f"Biggest moments hit {peak - base:.0f} dB above normal, {spikes} spike{'' if spikes == 1 else 's'}"
        + (f"; voice pitched up {lift * 100:.0f}% of the time" if lift is not None else "")
        + (f"; you can hear {', '.join(feels)}." if feels else "; no strong emotion in the words."),
        "This one is calm. Clips with a clear reaction (shock, laughing, rage, panic) get shared much more.")

    # Faster talking is linked to more shares in TikTok research; past ~4.5 words a second it gets hard to follow.
    rate = len(words) / max(length, 1)
    silent = float((db < base - 15).mean()) if len(db) else 1.0
    talk = min(1.0, rate / 2.5) if rate <= 4.5 else max(0.0, 1 - (rate - 4.5) / 3)
    pacing = 0.6 * talk + 0.4 * (1 - min(1.0, silent / 0.25))
    add("Pacing", pacing, 10, f"{rate:.1f} words a second, {silent * 100:.0f}% quiet.",
        "There are quiet stretches. Turn on Dead air > Cut out, or cut the slow part.")

    # Gaming clip tools find under ~20 s lacks setup for the payoff, over ~45 s loses people before the reaction.
    if 20 <= length <= 45:
        fit = 1.0
    elif length < 20:
        fit = max(0.0, (length - 8) / 12)
    else:
        fit = max(0.0, 1 - (length - 45) / 45)
    add("Length", fit, 10, f"{length:.0f} s long; 20 to 45 s is the sweet spot.",
        "Trim it toward 20 to 45 seconds." if length > 45 else "It's very short; give the moment a little setup.")

    # The best-performing clips are fast and their first frame is already interesting: the picture is moving.
    if motion is not None and len(motion):
        first = float(np.mean(motion[:2]))
        busy = float(np.mean(motion))
        visual = 0.5 * min(1.0, first / 0.08) + 0.5 * min(1.0, busy / 0.06)
        add("Visual pace", visual, 5, ("Moving from the first frame" if first >= 0.08 else "The first second is fairly still") +
            f"; the picture changes {'a lot' if busy >= 0.06 else 'a little'}.",
            "Open on movement: start where something is already happening on screen.")
    else:
        add("Visual pace", 0.5, 5, "Couldn't read the picture, so this part is neutral.")

    add("Captions and title", (0.6 if has_captions else 0) + (0.4 if has_title else 0), 5,
        ("Captions on" if has_captions else "No captions") + (", title on." if has_title else ", no title."),
        "Turn captions on: most people scroll with the sound off.")

    tail = db[int(len(db) * 0.75):] if len(db) else db
    payoff = min(1.0, max(0.0, (float(np.percentile(tail, 90)) - base + 2) / 8)) if len(tail) else 0.0
    # A clip whose last frame flows back into its first gets replayed, and replays count as rewatches.
    loops = loop is not None and loop >= 0.8
    add("Ends on the payoff", min(1.0, payoff + (0.4 if loops else 0.0)), 5,
        "The last quarter is " + ("as strong as the rest" if payoff >= 0.6 else "quieter than the rest")
        + ("; it loops cleanly back to the start." if loops else "."),
        "End the clip right after the big moment instead of letting it trail off.")

    score = sum(p["points"] for p in parts)
    # The three fixes worth the most points first.
    return Grade(score, _tier(score), parts, [t for _, t in sorted(tips, key=lambda x: -x[0])[:3]])

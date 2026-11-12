"""Find the moments in a long video most likely to work as short clips.

Two passes, so a 4-hour video takes minutes, not hours:
1. Sound and audience (whole video, fast). Loudness every 100 ms against the video's own local level finds
   reactions: yelling, laughing, a crowd, a big play. On YouTube, the "most replayed" graph (real viewers
   rewinding) is used too and outweighs everything else. Each peak becomes a candidate clip that opens a little
   before it (the setup, starting where there's already sound, so the first seconds hook) and ends just after
   it settles (the payoff), 15 to 60 seconds long.
2. Speech (best candidates only). What's said is transcribed: reaction phrases ("no way", "let's go", "bro"),
   a fast talking pace, and words in the first two seconds all count.
   For talk-heavy videos (podcasts, interviews) the words matter most: a clip that opens on a hook ("the
   craziest thing", a question) gains, one that opens mid-thought ("and", "but", "like I said") loses.
3. Picking: the best that don't overlap once snapped to sentences, spread through the video rather than five
   from one heated minute, and never the same moment twice (streamers often replay their own highlight, and
   a repeated line is the same clip). Each finished clip is then graded like every other clip.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

import numpy as np

STEP = 0.1  # seconds per loudness value
# Clipping tools that study gaming clips find under ~20 s lacks the setup for the payoff to land and over ~45 s
# loses viewers before the reaction; 60 s is the hard cap, used only when the payoff runs long.
MIN_LEN, TARGET_LEN, MAX_LEN = 20.0, 45.0, 60.0

HYPE = re.compile(r"\b(no way|oh my (god|gosh)|let'?s go+|what the|what\?|bro+|yo+|holy|are you serious|crazy|insane|"
                  r"wtf|oh no|dude|hell no|shut up|i can'?t|look at|did you see|ha(ha)+|lmao|lol|omg|wait|run|stop)\b", re.I)


@dataclass
class Moment:
    start: float
    end: float
    peak: float
    score: float  # 0..100
    why: list[str] = field(default_factory=list)
    text: str = ""

    def to_dict(self) -> dict:
        return {"start": round(self.start, 2), "end": round(self.end, 2), "peak": round(self.peak, 2),
                "score": round(self.score), "why": self.why, "text": self.text[:300]}


def _smooth(x: np.ndarray, n: int) -> np.ndarray:
    if len(x) < n or n <= 1:
        return x
    return np.convolve(x, np.ones(n) / n, mode="same")


def _local_level(db: np.ndarray, seconds: float = 60) -> np.ndarray:
    """The video's usual loudness around each point: a running median, so quiet and loud stretches are each
    judged against themselves."""
    n = max(1, int(seconds / STEP))
    step = max(1, n // 6)  # median every few seconds and spread out: plenty accurate, far faster
    idx = np.arange(0, len(db), step)
    meds = np.array([np.median(db[max(0, i - n // 2): i + n // 2 + 1]) for i in idx])
    return np.interp(np.arange(len(db)), idx, meds)


def heat_curve(heatmap: list[dict] | None, length: int) -> np.ndarray | None:
    """YouTube's most-replayed graph as a 0..1 value every 100 ms, or None."""
    if not heatmap:
        return None
    out = np.zeros(length)
    for h in heatmap:
        a, b = int(h.get("start_time", 0) / STEP), int(h.get("end_time", 0) / STEP)
        out[max(0, a):max(0, min(length, b))] = float(h.get("value") or 0)
    top = out.max()
    return out / top if top > 0 else None


def candidates(db: np.ndarray, heat: np.ndarray | None = None, limit: int = 20) -> list[Moment]:
    """Pass 1: the strongest-sounding (and most replayed) stretches, best first, never overlapping."""
    if len(db) < int(MIN_LEN / STEP):
        return []
    excite = _smooth(db - _local_level(db), int(1 / STEP))  # loudness above the surrounding level, 1 s smoothed
    signal = excite + (heat * 12 if heat is not None else 0)  # replayed parts stand out even when they're quiet
    # A steady talker never gets 4 dB above themselves: judge each video against its own loudest moments so a
    # podcast still gives candidates, while a loud stream keeps the usual bar.
    floor = min(4.0, max(1.5, float(np.percentile(signal, 97))))
    order = np.argsort(signal)[::-1]
    taken = np.zeros(len(db), bool)
    out: list[Moment] = []
    for i in order:
        if len(out) >= limit * 2 or signal[i] < floor:
            break
        if taken[i]:
            continue
        peak = i * STEP
        # Payoff: after the peak, until it has calmed down for 2 seconds (at most 15 s on).
        end = peak + 2
        calm = 0
        for k in range(i, min(len(db), i + int(15 / STEP))):
            calm = calm + 1 if excite[k] < 2 else 0
            end = k * STEP
            if calm >= int(2 / STEP):
                break
        # Setup: start 8 to 25 s before, at the point with the most sound in its first 2 s (the hook).
        best_start, best_hook = max(0.0, peak - 10), -1e9
        for back in np.arange(8, 25.5, 0.5):
            s = peak - back
            if s < 0:
                break
            a = int(s / STEP)
            hook = float(np.mean(db[a:a + int(2 / STEP)]))
            if hook > best_hook:
                best_start, best_hook = s, hook
        start = best_start
        end = max(end, start + MIN_LEN)
        if end - start > TARGET_LEN:  # trim the setup first, keeping the payoff whole
            start = max(start, min(peak - 5, end - TARGET_LEN))
        end = min(end, start + MAX_LEN, len(db) * STEP)
        a, b = int(start / STEP), int(end / STEP)
        if taken[a:b].any():
            continue
        taken[a:b] = True
        win = excite[a:b]
        peak_height = float(excite[i])
        spikes = int(((win[1:] > 8) & (win[:-1] <= 8)).sum())
        before = excite[max(0, i - int(10 / STEP)):i]
        contrast = peak_height - (float(np.mean(before)) if len(before) else 0)
        hook_lvl = float(np.mean(excite[a:a + int(3 / STEP)]))
        parts = {
            "peak": min(1.0, max(0.0, (peak_height - 5) / 15)),
            "spikes": min(1.0, spikes / max(1.0, (end - start) / 12)),
            "hook": min(1.0, max(0.0, (hook_lvl + 2) / 8)),
            "contrast": min(1.0, max(0.0, contrast / 12)),
        }
        weights = {"peak": 30, "spikes": 15, "hook": 15, "contrast": 10}
        why = []
        if parts["peak"] > 0.6:
            why.append(f"a big reaction ({peak_height:.0f} dB above the rest of that stretch)")
        if parts["contrast"] > 0.6:
            why.append("a quiet build-up that explodes")
        if parts["spikes"] > 0.6:
            why.append("several loud moments close together")
        score_max = sum(weights.values())
        score = sum(parts[k] * weights[k] for k in weights)
        if heat is not None:
            h = float(np.mean(heat[a:b]))
            score += 30 * h
            score_max += 30
            if h > 0.6:
                why.insert(0, "one of the most replayed parts of the video")
        out.append(Moment(start, end, peak, 100 * score / score_max, why))
    return sorted(out, key=lambda m: -m.score)[:limit]


def snap(m: Moment, words: list[tuple[float, float, str]], offset: float) -> None:
    """Start and end on whole sentences, so the clip opens on a complete thought and doesn't cut a word off.
    words: (start, end, text) in seconds from `offset` in the video, covering a little more than the moment."""
    if not words:
        return
    abs_words = [(offset + a, offset + b, t) for a, b, t in words]
    # A new thought starts after a pause or a sentence end. Pick the one nearest the planned start, but not
    # after the peak's setup (at most 3 s later) and not more than 6 s earlier.
    starts = [a for i, (a, _, _) in enumerate(abs_words)
              if i == 0 or a - abs_words[i - 1][1] > 0.35 or abs_words[i - 1][2].rstrip().endswith((".", "!", "?"))]
    ok = [a for a in starts if m.start - 6 <= a <= min(m.start + 3, m.peak - 5)]
    if ok:
        m.start = max(0.0, min(ok, key=lambda a: abs(a - m.start)) - 0.15)
    # End after the sentence being said when it would end, unless that runs past the hard cap.
    ends = [b for i, (_, b, t) in enumerate(abs_words)
            if t.rstrip().endswith((".", "!", "?")) or i == len(abs_words) - 1 or abs_words[i + 1][0] - b > 0.35]
    ok = [b for b in ends if m.end - 2 <= b <= m.start + MAX_LEN]
    if ok:
        m.end = min(ok, key=lambda b: abs(b - m.end)) + 0.3
    if m.end - m.start < MIN_LEN * 0.75:
        m.end = m.start + MIN_LEN * 0.75


HOOK = re.compile(r"^(\W*)(why|how|what|who|when|did you|have you|do you|the (craziest|worst|best|funniest|scariest)|"
                  r"i (never|can'?t believe|swear)|nobody|everyone|this is|imagine|story|so this|listen)\b", re.I)
DANGLING = re.compile(r"^(\W*)(and|but|so|because|cause|or|which|then|also|like i said|as i (said|mentioned)|anyway)\b", re.I)


def speech_bonus(m: Moment, words: list[tuple[float, float, str]], lift: float | None = None) -> None:
    """Pass 2: what's said and how. words are (start, end, text) in seconds from the moment's start; lift is the
    share of the voice pitched up (see grade.pitch_lift). Adds up to 25 points: final = 75% sound/audience +
    25% speech. What counts, from the research:
    - a reaction word right at the loud peak (sound plus keyword is the classic highlight signal),
    - high-arousal emotion: awe, amusement, anger, anxiety (what gets shared most),
    - a raised voice, a fast pace, and talking from the first second."""
    from .grade import arousal

    text = " ".join(w for _, _, w in words)
    m.text = text
    length = max(1.0, m.end - m.start)
    rel_peak = m.peak - m.start
    at_peak = " ".join(w for a, _, w in words if abs(a - rel_peak) <= 3)
    keyword_at_peak = bool(HYPE.search(at_peak))
    feels = arousal(text)
    pace = len(words) / length
    early = sum(1 for st, _, _ in words if st < 2)
    speech = (0.3 * (1.0 if keyword_at_peak else min(1.0, len(HYPE.findall(text)) / 4))
              + 0.25 * min(1.0, len(feels) / 2)
              + 0.15 * (min(1.0, lift / 0.25) if lift is not None else 0.5)
              + 0.15 * (min(1.0, pace / 2.5) if pace <= 4.5 else 0.7)
              + 0.15 * min(1.0, early / 3))
    if keyword_at_peak:
        m.why.append(f"\"{HYPE.search(at_peak).group(0)}\" right at the peak")
    if feels:
        m.why.append(f"{' and '.join(feels)} in what's said")
    if lift is not None and lift > 0.2:
        m.why.append("a raised, excited voice")
    if early >= 3:
        m.why.append("talking from the first second")
    opening = " ".join(w for _, _, w in words[:6])
    if words and HOOK.search(opening):
        speech += 0.15
        m.why.append("opens on a hook")
    elif words and DANGLING.search(opening):
        speech -= 0.2  # starts mid-thought: the viewer is missing what came before
    m.score = 0.75 * m.score + 25 * max(0.0, min(1.0, speech))


def _same_words(a: str, b: str) -> bool:
    x, y = set(re.findall(r"[a-z']{3,}", a.lower())), set(re.findall(r"[a-z']{3,}", b.lower()))
    return len(x) >= 12 and len(y) >= 12 and len(x & y) / len(x | y) > 0.5


def pick(moments: list[Moment], count: int, spread: float = 180.0) -> list[Moment]:
    """The best `count`, in the order they happen in the video. Greedy by score, skipping any that overlap one
    already picked (sentence snapping can move edges) or repeat its words; one within `spread` seconds of a
    pick counts for 20% less, so the clips cover the whole video unless one stretch really is that good."""
    left, chosen = list(moments), []
    while left and len(chosen) < count:
        def value(m: Moment) -> float:
            near = any(abs(m.peak - c.peak) < spread for c in chosen)
            return m.score * (0.8 if near else 1.0)
        best = max(left, key=value)
        left.remove(best)
        if any(best.start < c.end and c.start < best.end for c in chosen) or any(_same_words(best.text, c.text) for c in chosen):
            continue
        chosen.append(best)
    return sorted(chosen, key=lambda m: m.start)


def title_for(m: Moment, fallback: str) -> str:
    """A short title from the line said closest to the peak, else the video's own title."""
    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", m.text) if len(s.strip().split()) >= 3]
    hyped = [s for s in sentences if HYPE.search(s)]
    line = (hyped or sentences or [""])[0]
    line = " ".join(line.split()[:10]).strip(" ,")
    return (line[:1].upper() + line[1:]) if line else fallback

"""Titles: the line on the video, the post's title and its caption, all the same. Never the Twitch clip's title or
the source post's caption copied over: those are someone else's words, usually flat ("lol", "W", "clip").

Two kinds, both built only from what happens in the clip, so the video always delivers what the title promises:
1. A quote: the most striking thing said, word for word, in quotes, with an emoji ("“He really just did that” 😭").
   Picked from the transcript: reaction words, strong emotion, short enough to read at a glance, said at or near
   the big moment, and not a mid-thought fragment.
2. A summary with a little pull: what kind of moment it is, with the streamer's name ("Kai could NOT stop laughing
   😭", "Lacy was not ready for this 💀"). Chosen from the clip's mood (laughing, shock, anger, fear), so it fits.
The quote wins when the clip has a good line; otherwise the summary.
"""
from __future__ import annotations

import re
import zlib

from .describe import has_name
from .grade import arousal
from .moments import HYPE

FILLER_ONLY = re.compile(r"^(?:(?:yeah|yea|ok|okay|uh|um|like|so|and|but|the|a|i|it|that|lol|lmao|ha(?:ha)+h?|bro|dude|man|oh|what)\W*\s*)+$", re.I)
DANGLING = re.compile(r"^(and|but|so|because|cause|or|then|which|like i said)\b", re.I)
SHOCK = re.compile(r"\b(wtf|what the|no way|are you serious|oh my god|omg|holy|wait what|bro what|insane|crazy|i can'?t believe)\b", re.I)
LAUGH = re.compile(r"\b(ha(ha)+|lmao|lmfao|i'?m crying|dead|i can'?t breathe|that'?s so funny)\b", re.I)

# Summaries by mood. {n} is the streamer. Each says what kind of moment it is, nothing the clip doesn't show.
SUMMARIES = {
    "laugh": ["{n} could NOT stop laughing 😭", "{n} lost it at this 😭", "This had {n} crying laughing 😭"],
    "shock": ["{n} was not ready for this 💀", "{n} couldn't believe what just happened 😳", "Nobody saw this coming, not even {n} 💀"],
    "anger": ["{n} was NOT having it 😤", "{n} went off after this 😤"],
    "fear": ["{n} got so scared 😬", "This had {n} panicking 😬"],
    "hype": ["{n} went crazy after this 🔥", "{n}'s reaction says it all 🔥"],
    "plain": ["{n}'s reaction to this 😳", "Wait for {n}'s reaction 👀"],
}
EMOJI = {"laugh": "😭", "shock": "💀", "anger": "😤", "fear": "😬", "hype": "🔥", "plain": "😳"}


def _mood(text: str) -> str:
    feels = arousal(text)
    if LAUGH.search(text) or "amusement" in feels:
        return "laugh"
    if SHOCK.search(text) or "awe" in feels:
        return "shock"
    if "anger" in feels:
        return "anger"
    if "anxiety" in feels:
        return "fear"
    return "hype" if HYPE.search(text) else "plain"


def sentences(words: list) -> list[tuple[float, str]]:
    """(start time, text) for each sentence: split on end punctuation or a pause of more than 0.6 s."""
    out, cur, t0 = [], [], 0.0
    for i, w in enumerate(words):
        if not cur:
            t0 = w.start
        cur.append(w.text)
        end = w.text.rstrip().endswith((".", "!", "?")) or i + 1 == len(words) or words[i + 1].start - w.end > 0.6
        if end:
            out.append((t0, " ".join(cur).strip()))
            cur = []
    return out


def best_quote(words: list, peak: float | None = None) -> tuple[str, float] | None:
    """The most striking line said, with its score, or None if nothing is worth quoting."""
    best = None
    for t, s in sentences(words):
        clean = s.strip(" ,;:-\"“”")
        n = len(clean.split())
        if not 2 <= n <= 12 or FILLER_ONLY.match(clean) or DANGLING.match(clean):
            continue
        score = (3.0 * len(HYPE.findall(clean)) + 2.0 * len(arousal(clean)) + (2.0 if SHOCK.search(clean) else 0)
                 + (1.0 if clean.endswith(("!", "?")) else 0) + (1.0 if 4 <= n <= 9 else 0)
                 + (3.0 if peak is not None and abs(t - peak) <= 4 else 0))
        if best is None or score > best[1]:
            best = (clean, score)
    return best if best and best[1] >= 5 else None


def make_title(words: list, creator: str | None, peak: float | None = None, names: list[str] = ()) -> tuple[str, bool]:
    """(title, is a quote). words: the transcript (start, end, text); peak: seconds of the big moment, if known.
    names: what a campaign wants named on the video; any the title doesn't say are added."""
    said = " ".join(w.text for w in words)
    mood = _mood(said)
    quote = best_quote(words, peak)
    if quote:
        line = quote[0].rstrip(".")
        letters = [ch for ch in line if ch.isalpha()]
        if letters and sum(ch.isupper() for ch in letters) / len(letters) > 0.6:  # all caps reads as shouting
            line = line.lower()
            if creator:
                line = re.sub(re.escape(creator), creator, line, flags=re.I)
        line = line[:1].upper() + line[1:]
        title = f"“{line}” {EMOJI[_mood(line) if _mood(line) != 'plain' else mood]}"
        missing = [n for n in names if not has_name(title, n)]
        return (f"{' and '.join(missing)}: {title}" if missing else title), True
    options = SUMMARIES[mood]
    pick = options[zlib.crc32(said.encode()) % len(options)]  # varied across clips, the same for one clip every time
    who = (creator or "The streamer").strip()
    if not all(has_name(who, n) for n in names):  # the campaign's name for the streamer is the one on screen
        who = " and ".join(names)
    return pick.format(n=who), False

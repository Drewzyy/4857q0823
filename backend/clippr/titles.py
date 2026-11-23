"""Titles: the line on the video, the post's title and its caption, all the same. Never the Twitch clip's title or
the source post's caption copied over: those are someone else's words, usually flat ("lol", "W", "clip").

Written the way people who run clip pages write, not the way an ad does: lower case, plain words, no exclamation
marks, no CAPS for emphasis, and no emoji tacked on (a page's own signature emoji is added only if you set one).
Two kinds, both built only from what happens in the clip, so the video always delivers what the title promises:
1. The line itself: the most striking thing said, word for word, with the filler at the front taken off
   ("bro, like, he really just did that" -> "he really just did that"). Picked from the transcript: a real
   sentence (not a fragment or a laugh), said at or near the big moment, short enough to read at a glance. Shown
   as a quote, as the streamer's quote, or bare, varied from clip to clip.
2. If nothing said lands, a short understated line about the kind of moment, with the streamer's name
   ("kai did not see that coming", "lacy was not having it"). Understatement reads as a person; hype reads as a bot.
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

# Summaries by mood, understated on purpose. {n} is the streamer. Each says what kind of moment it is, nothing the clip
# doesn't show. Several per mood so a page of clips doesn't repeat itself.
SUMMARIES = {
    "laugh": ["{n} could not keep it together", "{n} lost it at this one", "this one got {n}", "{n} was crying at this",
              "{n} tried not to laugh", "it took {n} a minute to recover from this"],
    "shock": ["{n} did not see that coming", "nobody saw this coming, {n} included", "{n} needed a second after this",
              "{n} was speechless", "wait for {n}'s reaction", "{n} could not believe it"],
    "anger": ["{n} was not having it", "{n} had enough", "{n} was done after this", "this set {n} off"],
    "fear": ["{n} jumped so hard", "{n} was not ready", "{n} got scared for real", "this had {n} on edge"],
    "hype": ["{n} actually pulled it off", "{n} went off after this", "chat could not believe {n} did this", "{n} was locked in"],
    "plain": ["{n} had a moment", "{n} explains", "{n} on this", "wait for the end", "{n} meant every word"],
}
# A title never swears (platforms show it to fewer people and it says nothing) and is never only a reaction: "what
# the fuck", "oh my god", "no way bro" fit any clip, so they tell a viewer nothing about this one.
PROFANE = re.compile(r"\b(fuck\w*|f+ck\w*|shit\w*|bitch\w*|ass(hole)?|dick\w*|cunt|bastard|damn|goddamn|piss\w*|motherf\w*|wtf|stfu|"
                     r"n[i1]gg\w*|f[a4]gg?\w*|retard\w*|whore|slut)\b", re.I)
REACTION = {"what", "the", "no", "way", "oh", "my", "god", "gosh", "bro", "bruh", "dude", "holy", "yes", "yeah", "let's", "lets", "go", "come",
            "on", "dawg", "man", "chat", "guys", "omg", "lol", "lmao", "wow", "wait", "stop", "please", "nah", "yo", "huh", "really",
            "actually", "literally", "is", "this", "that", "are", "you", "serious", "kidding", "me", "it", "a", "so", "i", "can't", "cant",
            "believe", "just", "happened", "insane", "crazy", "unbelievable", "ridiculous", "he", "she", "they", "him", "her", "did", "do",
            "done", "doing", "right", "now", "there", "here", "we", "us", "be", "was", "were", "not", "to", "of", "in", "at", "like"}
FILLER_START = re.compile(r"^(?:(?:bro|bruh|yo|dude|man|like|so|okay|ok|um|uh|and|but|oh|wait|guys|chat|listen|look|yeah|nah)\b[,.!]?\s*)+", re.I)


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


def casual(line: str, names: list[str] = ()) -> str:
    """How a person would type it: filler off the front, lower case (names and "I" kept), no shouting, no end stop."""
    line = FILLER_START.sub("", line.strip(" ,;:-\"“”")).strip(" ,;:-")
    line = re.sub(r"[!?.]+$", lambda m: "?" if "?" in m.group() else "", line).strip()
    line = re.sub(r"\s+", " ", line.lower())
    line = re.sub(r"\bi\b", "I", line)
    line = re.sub(r"\bi('(?:m|ll|ve|d))\b", r"I\1", line)
    for n in names:
        if n:
            line = re.sub(rf"(?<!\w){re.escape(n.lower())}(?!\w)", n, line)
    return line


def best_quote(words: list, peak: float | None = None) -> tuple[str, float] | None:
    """The most striking line said, with its score, or None if nothing is worth quoting."""
    best = None
    for t0, s in sentences(words):
        clean = FILLER_START.sub("", s.strip(" ,;:-\"“”")).strip(" ,;:-")
        n = len(clean.split())
        if not 3 <= n <= 12 or FILLER_ONLY.match(clean) or DANGLING.match(clean) or LAUGH.fullmatch(clean.lower().strip(" !.")):
            continue
        if PROFANE.search(clean):
            continue
        said = [w for w in re.findall(r"[a-z']+", clean.lower()) if w not in REACTION]
        if len(said) < 2:  # only a reaction: nothing about what happened
            continue
        score = (2.0 * len(HYPE.findall(clean)) + 2.0 * len(arousal(clean)) + (1.0 if SHOCK.search(clean) else 0) + 1.0 * min(len(said), 4)
                 + (1.0 if clean.endswith(("!", "?")) else 0) + (1.5 if 4 <= n <= 9 else 0)
                 + (1.0 if re.search(r"\b(I|you|he|she|they|we)\b", clean, re.I) else 0)  # someone did something: a story, not a noise
                 + (3.0 if peak is not None and abs(t0 - peak) <= 4 else 0))
        if best is None or score > best[1]:
            best = (clean, score)
    return best if best and best[1] >= 7 else None  # only a line that clearly lands; otherwise a summary of the moment


def make_title(words: list, creator: str | None, peak: float | None = None, names: list[str] = ()) -> tuple[str, bool]:
    """(title, is a quote). words: the transcript (start, end, text); peak: seconds of the big moment, if known.
    names: what a campaign wants named on the video; any the title doesn't say are added."""
    said = " ".join(w.text for w in words)
    mood = _mood(said)
    pick = zlib.crc32(said.encode())  # varied across clips, the same for one clip every time
    who = (creator or "").strip()
    quote = best_quote(words, peak)
    if quote:
        line = casual(quote[0], [who, *names])
        missing = [n for n in names if not has_name(line, n)]
        if missing:
            return f"{' and '.join(missing)}: “{line}”", True
        style = pick % 3
        if style == 1 and who:
            return f"{who.lower() if who.islower() else who}: “{line}”", True
        return (line if style == 2 else f"“{line}”"), True
    options = SUMMARIES[mood]
    name = who or "the streamer"
    if names and not all(has_name(name, n) for n in names):  # the campaign's name for the streamer is the one on screen
        name = " and ".join(names)
    line = options[pick % len(options)].format(n=name)
    return (line[:1].upper() + line[1:] if line.startswith("the streamer") else line), False


def shouts(text: str) -> bool:
    """True if the text has an emoji or shouting in it (what a title shouldn't have unless the page adds its own)."""
    letters = [c for c in text if c.isalpha()]
    return bool(re.search("[\U0001F000-\U0001FAFF\u2600-\u27BF]", text)) or (len(letters) > 8 and sum(c.isupper() for c in letters) / len(letters) > 0.5)


def said_at(words: list, title: str) -> float | None:
    """When the line a quote title is made of starts in the clip (seconds, same clock as words), or None."""
    want = re.sub(r"[^a-z0-9 ]", "", title.lower())
    for t0, s in sentences(words):
        line = re.sub(r"[^a-z0-9 ]", "", casual(s).lower())
        if line and line in want:
            return t0
    return None

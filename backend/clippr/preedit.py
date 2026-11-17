"""Vyral's viral pre-edit: what every new clip gets before it shows up in Ready to Upload.

Modeled on eight streamer clips from clip pages that each passed 200k views (studied frame by frame and by
ear, November 2026). What they shared:
- Length: seven of eight ran 18 to 28 seconds. Longer cuts are trimmed to the strongest stretch, kept whole
  around the loudest moment so the payoff lands.
- They open on sound: the first sound comes within the first quarter second. Lead-in silence is cut.
- One headline for the whole clip, at the top, in dark text on a white box, in plain sentence case:
  "Lacy couldn't believe Dani from Outside drank a random person's drink 😭". Third person, names the
  streamer, says what happens without giving away the payoff, and ends on one or two emoji.
- Gaming clips put the streamer's face on top and the game under it, headline on the seam.
- Almost no cuts (one or two in a 20-second clip), no zooms, no music. None of the 18 had sound effects; Vyral
  adds one at most, on the biggest moment, and only when something clearly stands out (Settings can turn it off).
The page's own title style is left off when the headline is used, so there's one title, not two. Captions
follow the page's setting. Everything here shows in the editor, where it can be changed or removed.
"""
from __future__ import annotations

import re

import numpy as np

from .describe import clean_title
from .grade import arousal
from .media.facecam import CAM_SHARE

VERSION = 2  # 2: sound effects, quote headlines, up to 45 s
STEP = 0.1
LONGEST = 45.0      # trimmed when longer than this (half the second batch of top clips ran 35 to 50 s)
TARGET = 34.0       # length of the trimmed clip: room for the setup, still short enough to finish
SHORTEST = 12.0     # never trimmed below this
HEADLINE_Y = 17     # % from the top
QUOTE_Y, QUOTE_SIZE = 58, 66  # a quote headline: white, mid-frame
HEADLINE_SIZE = 76  # pixels on a 1080-wide video: about 3% of the height per line, like the top clips
EMOJI = {"amusement": "😭", "awe": "😳", "anger": "😤", "anxiety": "😬"}
SHOCK = re.compile(r"\b(wtf|what the|no way|bro|oh my god|omg|are you serious|insane|crazy)\b", re.I)
HAS_EMOJI = re.compile("[\U0001F300-\U0001FAFF☀-➿]")


def _sentence_case(text: str, creator: str | None) -> str:
    """ALL CAPS reads as shouting: it becomes a normal sentence, keeping the streamer's name capitalized."""
    letters = [ch for ch in text if ch.isalpha()]
    if not letters or sum(ch.isupper() for ch in letters) / len(letters) <= 0.6:
        return text
    text = text.lower()
    text = text[:1].upper() + text[1:]
    return re.sub(re.escape(creator), creator, text, flags=re.I) if creator else text


def headline(post_title: str, clip_title: str, creator: str | None, speech: str = "") -> str:
    return plan_headline(post_title, clip_title, creator, speech)[0]


def plan_headline(post_title: str, clip_title: str, creator: str | None, speech: str = "") -> tuple[str, bool]:
    """(headline, is_quote). The source post's own caption is used when it's a real sentence (other clip pages
    write exactly this kind of line) and goes in the white box. Otherwise the line said in the clip is quoted,
    which top pages show as plain white text across the middle: "You're not growing" 😭❤️."""
    base = _sentence_case(clean_title(post_title or "", None), creator) if post_title else ""
    quote = False
    if len(base.split()) < 4 or base.lower().startswith(("stream moment", "clip")):
        line = _sentence_case(clean_title(clip_title or "", None), creator).strip(" “”\"")
        quote = bool(line) and len(line.split()) <= 12
        base = f"“{line.rstrip('.')}”" if quote else (line or (f"{creator} moment" if creator else ""))
    base = base[:100].rstrip(" ,;:-")
    if not HAS_EMOJI.search(base):
        text = f"{base} {speech}"
        feels = arousal(text)
        mark = "💀" if SHOCK.search(text) and not feels else EMOJI.get(feels[0], "😳") if feels else "😳"
        base = f"{base} {mark}"
    return base, quote


def best_window(db: np.ndarray | None, words: list, dur: float) -> tuple[float, float]:
    """(start, end) in seconds from the clip's start: the whole clip, or for a long one the TARGET-second stretch
    ending just after its loudest moment, opening on a new sentence. Always starts on sound."""
    start, end = 0.0, dur
    if db is not None and len(db) > int(SHORTEST / STEP) and dur > LONGEST:
        level = np.convolve(db - np.median(db), np.ones(10) / 10, mode="same")
        peak = float(np.argmax(level[: int((dur - 1) / STEP)])) * STEP
        end = min(dur, max(peak + 4.0, TARGET))
        # Settle the payoff: finish the sentence being said.
        later = [w.end for w in words if peak < w.end <= end + 3]
        if later:
            end = min(dur, max(end, later[-1] + 0.3) if later[-1] - peak < 8 else end)
        start = max(0.0, end - TARGET)
        firsts = [w.start for i, w in enumerate(words)
                  if start - 2 <= w.start <= min(start + 4, peak - 6)
                  and (i == 0 or w.start - words[i - 1].end > 0.35 or words[i - 1].text.rstrip().endswith((".", "!", "?")))]
        if firsts:
            start = max(0.0, min(firsts, key=lambda a: abs(a - start)) - 0.1)
    # Open on sound: the first word, or the first moment that isn't near silence.
    first_word = next((w.start for w in words if w.start >= start), None)
    first_sound = None
    if db is not None and len(db):
        a = int(start / STEP)
        loud = np.nonzero(db[a:] > np.median(db) - 12)[0]
        first_sound = start + loud[0] * STEP if len(loud) else None
    found = [x for x in (first_word, first_sound) if x is not None]
    lead = min(min(found), start + 5.0) if found else start  # a long silent opening is more likely a problem than intent
    if lead - start > 0.3:
        start = lead - 0.15
    if end - start < SHORTEST:
        start = max(0.0, end - SHORTEST)
    return round(start, 2), round(end, 2)


def auto_sound(db: np.ndarray | None, a: float, b: float, speech: str) -> tuple[str, float] | None:
    """One sound effect for the biggest moment in [a, b) (seconds from the clip's start), or None when nothing
    stands out enough to deserve one. (name, when it starts.) A riser starts early so it peaks on the moment."""
    if db is None or len(db) < 20:
        return None
    i, j = int(a / STEP), min(len(db), int(b / STEP))
    level = np.convolve(db - np.median(db[i:j]), np.ones(5) / 5, mode="same")[i:j]
    if not len(level) or level.max() < 8:  # a calm clip: a sound effect would feel forced
        return None
    peak = a + float(np.argmax(level)) * STEP
    if peak - a < 1.0 or b - peak < 0.5:
        return None  # right at an edge, it would cover the hook or get cut off
    feels = arousal(speech)
    if "anxiety" in feels and peak - a > 2.5:
        return "riser", round(peak - 1.5, 2)
    if SHOCK.search(speech) or "awe" in feels:
        return "bass_drop", round(peak, 2)
    return "boom", round(peak, 2)


def apply(edit: dict, words: list, db: np.ndarray | None, headline_text: str, quote: bool = False, sound: bool = False) -> dict:
    """The pre-edit on a clip's edit (start/end in source seconds; words and db from edit['start'])."""
    e = dict(edit)
    if e.get("preedit_version", 1 if e.get("preedited") else 0) >= VERSION:
        return e
    dur = e["end"] - e["start"]
    a, b = best_window(db, words, dur)
    e["start"], e["end"] = round(e["start"] + a, 3), round(e["start"] + b, 3)
    texts = [t for t in e.get("texts") or [] if not (t.get("box") or t.get("headline"))]
    if headline_text:
        stacked = e.get("layout") == "stacked" and e.get("cam")
        if quote:  # white words across the middle, above where the captions run
            texts.insert(0, {"text": headline_text[:200], "start": 0, "end": round(b - a + 1, 2), "y_percent": QUOTE_Y,
                             "size": QUOTE_SIZE, "color": "#FFFFFF", "font": "poppins", "all_caps": False, "outline": 5, "headline": True})
        else:
            # With the facecam on top, the headline sits on the seam between face and gameplay, as the top gaming clips do.
            y = round(CAM_SHARE * 100) if stacked else HEADLINE_Y
            texts.insert(0, {"text": headline_text[:200], "start": 0, "end": round(b - a + 1, 2), "y_percent": y, "size": HEADLINE_SIZE,
                             "color": "#141414", "font": "poppins", "all_caps": False, "outline": 0, "box": True, "headline": True})
        e["hide_title"] = True
    if sound and not e.get("sounds"):
        pick = auto_sound(db, a, b, " ".join(w.text for w in words))
        if pick:
            e["sounds"] = [{"name": pick[0], "at": round(edit["start"] + pick[1], 3), "volume": 0.6}]
    e["texts"] = texts[:20]
    e["preedited"], e["preedit_version"] = True, VERSION
    return e


def caption_source(headline_text: str, post_title: str) -> str:
    """What the post caption is built from: the headline (what it's about, which TikTok and Instagram search
    read) plus the source post's own hashtags. Falls back to the source post when there's no headline."""
    if not headline_text:
        return post_title
    tags = " ".join(re.findall(r"#\w+", post_title or ""))
    return f"{headline_text} {tags}".strip()

"""Vyral's viral pre-edit: what every new clip gets before it shows up in Ready to Upload.

Modeled on eight streamer clips from clip pages that each passed 200k views (studied frame by frame and by
ear, November 2026). What they shared:
- Length: seven of eight ran 18 to 28 seconds. Longer cuts are trimmed to the strongest stretch, kept whole
  around the loudest moment so the payoff lands.
- They open on sound: the first sound comes within the first quarter second. Lead-in silence is cut.
- One headline at the top, in dark text on a white box, in plain sentence case, for the opening seconds only
  (it says what's happening, then gets out of the way of the picture):
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

from . import titles
from .grade import arousal
from .media.facecam import CAM_SHARE

VERSION = 10  # 2: sound effects, quote headlines, up to 45 s. 3: hook up front. 4: punch-in on the peak. 5: own titles, climax trim.
# 6: at least 25 s with setup (screen.py), the headline at the top for the opening seconds only, then gone.
# 7: titles written like a person (titles.py): the line said, lower case, no emoji or hype.
# 8: a headline only when it adds something (a line said later in the clip); otherwise none.
# 9: your answers: 35 s to 1:20 (aim 45 s to a minute), a 2-4 s hook, the reaction played out, caps headline.
# 10: captions tag the streamer's channel (@jasontheween); every waiting clip redone, edited ones too
REDO_EDITED_BELOW = 10  # clips you edited are redone too when they're older than this
STEP = 0.1
LONGEST = 80.0      # trimmed when longer than this (what you asked for: 35 s to 1:20, most 45 s to a minute)
TARGET = 52.0       # length of a trimmed clip: the whole setup and the reaction played out (a minute or more also earns money)
SHORTEST = 35.0     # never trimmed below this (screen.py: shorter has no room for the setup)
HEADLINE_Y = 17     # % from the top
HEADLINE_LEAD = 4.0  # a line said within this many seconds of the start needs no headline: it's heard right away
TITLE_SECONDS = 4.0  # the headline shows for the opening seconds (after the hook), then gets out of the way
HEADLINE_SIZE = 76  # pixels on a 1080-wide video: about 3% of the height per line, like the top clips
SHOCK = re.compile(r"\b(wtf|what the|no way|bro|oh my god|omg|are you serious|insane|crazy)\b", re.I)


def best_window(db: np.ndarray | None, words: list, dur: float, min_s: float = 0, max_s: float = 0,
                style: dict | None = None) -> tuple[float, float]:
    """(start, end) in seconds from the clip's start: the whole clip, or for a long one the TARGET-second stretch
    ending just after its loudest moment, opening on a new sentence. Always starts on sound. min_s and max_s are a
    campaign's length rules (0 = none): the window is kept inside them, and is only shorter than min_s when the
    clip itself is. style: your learned style (style.py): its usual length range and length replace the defaults."""
    hi = max_s or float("inf")
    defaults = (style["length_low"], style["length_high"], style["length"]) if style else (SHORTEST, LONGEST, TARGET)
    shortest, longest, target = (min(max(x, min_s), hi) for x in defaults)
    start, end = 0.0, dur
    if db is not None and len(db) > int(shortest / STEP) and dur > longest:
        level = np.convolve(db - np.median(db), np.ones(10) / 10, mode="same")
        peak = float(np.argmax(level[: int((dur - 1) / STEP)])) * STEP
        end = min(dur, max(peak + 4.0, target))
        # Settle the payoff: finish the sentence being said.
        later = [w.end for w in words if peak < w.end <= end + 3]
        if later:
            end = min(dur, max(end, later[-1] + 0.3) if later[-1] - peak < 8 else end)
        start = max(0.0, end - target)
        firsts = [w.start for i, w in enumerate(words)
                  if start - 2 <= w.start <= min(start + 4, peak - 6)
                  and (i == 0 or w.start - words[i - 1].end > 0.35 or words[i - 1].text.rstrip().endswith((".", "!", "?")))]
        if firsts:
            start = max(0.0, min(firsts, key=lambda a: abs(a - start)) - 0.1)
    # The climax: on any clip with a clear peak, end once it has settled (the reaction plays out, then cut: no
    # trailing chatter, a few seconds after it), and keep up to ~45 s of build-up: the context is the point.
    peak = peak_moment(db, start, end)
    if peak is not None:
        level = np.convolve(db - np.median(db), np.ones(10) / 10, mode="same")
        calm = next((k * STEP for k in range(int((peak + 2) / STEP), int(end / STEP)) if (level[k:k + 15] < 2).all()), None)
        if calm is not None and end - calm > 3:
            spoken = [w.end for w in words if calm - 1 <= w.end <= calm + 2.5]  # finish the sentence being said
            end = round(min(end, (max(spoken) if spoken else calm) + 3.0), 2)  # let the reaction play out
        if peak - start > 50:
            starts = [w.start for i, w in enumerate(words) if peak - 45 <= w.start <= peak - 20
                      and (i == 0 or w.start - words[i - 1].end > 0.35 or words[i - 1].text.rstrip().endswith((".", "!", "?")))]
            start = (min(starts) - 0.1) if starts else peak - 45
        if style and style.get("tail") is not None and style.get("peak_share") is not None:
            # Cut from the stream the way yours are: as much setup before the moment and as much after it as your
            # clips have (where the big moment sits in them), at your usual length.
            whole = peak_moment(db, 0, dur) or peak
            after = min(style["tail"], max(3.0, target * (1 - style["peak_share"])))
            end = round(min(dur, whole + after), 2)
            start = round(max(0.0, end - target), 2)
            starts = [w.start for i, w in enumerate(words) if start - 3 <= w.start <= start + 3
                      and (i == 0 or w.start - words[i - 1].end > 0.35 or words[i - 1].text.rstrip().endswith((".", "!", "?")))]
            if starts:  # open on a new sentence
                start = max(0.0, min(starts, key=lambda a: abs(a - start)) - 0.1)
    if end - start < shortest:
        start = max(0.0, end - shortest)
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
    if min_s and end - start < min(min_s, hi):  # the clip was ended early (the climax settled): the campaign wants more, if there is any
        end = min(dur, start + min(min_s, hi))
    if end - start > hi:  # the climax trim or the sound opening can leave more than the campaign allows
        start = end - hi
    return round(start, 2), round(end, 2)


def peak_moment(db: np.ndarray | None, a: float, b: float) -> float | None:
    """When the biggest moment in [a, b) happens (seconds from the clip's start), or None when nothing clearly
    stands out, or it's right at an edge (it would cover the hook or get cut off)."""
    if db is None or len(db) < 20:
        return None
    i, j = int(a / STEP), min(len(db), int(b / STEP))
    level = np.convolve(db - np.median(db[i:j]), np.ones(5) / 5, mode="same")[i:j]
    if not len(level) or level.max() < 8:
        return None
    peak = a + float(np.argmax(level)) * STEP
    return peak if peak - a >= 1.0 and b - peak >= 0.5 else None


def auto_sound(db: np.ndarray | None, a: float, b: float, speech: str) -> tuple[str, float] | None:
    """One sound effect for the biggest moment, or None when a sound effect would feel forced. (name, when it
    starts.) A riser starts early so it peaks on the moment."""
    peak = peak_moment(db, a, b)
    if peak is None:
        return None
    feels = arousal(speech)
    if "anxiety" in feels and peak - a > 2.5:
        return "riser", round(peak - 1.5, 2)
    if SHOCK.search(speech) or "awe" in feels:
        return "bass_drop", round(peak, 2)
    return "boom", round(peak, 2)


HOOK_MIN, HOOK_MAX = 2.0, 4.0  # the climax up front for 2 to 4 seconds, then the story from its start


def pick_hook(db: np.ndarray | None, words: list, a: float, b: float, lengths: tuple = (2.5, 3.0, 4.0)) -> tuple[float, float] | None:
    """The best few seconds of [a, b) (seconds from the clip's start) to show first, or None when the clip already
    opens on its best part or nothing stands out. Scored on the reaction (loudness against the clip's own level,
    how sharp the spike is) and on what's said (reaction words, fast talking). Snapped to whole words."""
    from .moments import HYPE
    if db is None or b - a < 15:
        return None
    i, j = int(a / STEP), min(len(db), int(b / STEP))
    level = db[i:j] - np.median(db[i:j])

    def score(s0: float, s1: float) -> float:
        seg = level[int((s0 - a) / STEP):int((s1 - a) / STEP)]
        if not len(seg):
            return -1e9
        said = " ".join(w.text for w in words if s0 <= w.start < s1)
        return (float(np.percentile(seg, 90)) + 0.5 * float(seg.mean()) + 4 * len(HYPE.findall(said))
                + 1.5 * min(3.0, sum(1 for w in words if s0 <= w.start < s1) / max(1.0, s1 - s0)))

    opening = score(a, a + 5)
    best, at = -1e9, None
    for t in np.arange(a + 6, b - HOOK_MIN, 0.5):  # never the opening itself: that's already first
        for length in lengths:
            if t + length <= b:
                v = score(t, t + length)
                if v > best:
                    best, at = v, (float(t), float(t + length))
    if at is None or best < opening + 3 or float(np.percentile(level, 99)) < 6:
        return None  # the opening is as good, or the clip is flat: a hook wouldn't earn its place
    s0, s1 = at
    # Whole words: start on the word nearest the window's start, end after the word running at its end.
    starts = [w.start for w in words if s0 - 1 <= w.start <= s0 + 1]
    if starts:
        s0 = max(a, min(starts, key=lambda x: abs(x - at[0])) - 0.1)
    ends = [w.end for w in words if s1 - 1 <= w.end <= s1 + 1.5]
    if ends:
        s1 = min(b, min(ends, key=lambda x: abs(x - at[1])) + 0.15)
    s1 = min(s1, s0 + HOOK_MAX + 0.5)
    return (round(s0, 2), round(s1, 2)) if s1 - s0 >= HOOK_MIN else None


def apply(edit: dict, words: list, db: np.ndarray | None, headline_text: str, quote: bool = False, sound: bool = False,
          choice: str = "", hook: bool = False, min_s: float = 0, max_s: float = 0, named: bool = False,
          style: dict | None = None) -> dict:
    """The pre-edit on a clip's edit (start/end in source seconds; words and db from edit['start']).
    choice: the sound to use on big moments (Settings), "" to pick one by the moment. min_s, max_s: a campaign's
    length rules (best_window); the teaser counts toward the length, so it's left out when it wouldn't fit.
    named: a campaign wants names on the video, so the headline stays whatever it is.
    style: your learned style (style.py), once enough of your clips are measured: your length, whether your clips
    have a hook (and how long), a headline (and for how long), sound effects and captions, instead of the defaults."""
    e = dict(edit)
    if e.get("preedit_version", 1 if e.get("preedited") else 0) >= VERSION:
        return e
    dur = e["end"] - e["start"]
    a, b = best_window(db, words, dur, min_s, max_s, style)
    title_for = TITLE_SECONDS
    if style:
        hook = hook and style["hook_rate"] >= 0.5  # most of your clips open on the climax: so does this one
        sound = sound and style["sfx_rate"] >= 0.5
        choice = choice or style.get("sound") or ""  # the sound effect your clips use
        title_for = style["headline_seconds"] or TITLE_SECONDS
        if style["captions_rate"] < 0.3:
            e["captions"] = False  # yours don't have captions
    e["start"], e["end"] = round(e["start"] + a, 3), round(e["start"] + b, 3)
    texts = [t for t in e.get("texts") or [] if not (t.get("box") or t.get("headline"))]
    # Not every clip needs a title on the video. When someone is talking, text over the picture competes with them
    # (Emplifi's Reels data: overlays lowered retention on speech-led videos, helped on music-led ones), and the
    # captions already show what's said. So the headline goes on only when it adds something: a line said later in
    # the clip, shown up front as the reason to keep watching. A summary that fits any clip ("kai had a moment") or a
    # line the clip opens on anyway is left off the picture and kept for the post's caption.
    said = titles.said_at(words, headline_text) if headline_text and quote else None
    usual = style["headline_rate"] if style else None  # how often your clips have one
    if named or (usual is not None and usual >= 0.6):
        pass  # a campaign wants a name on the video, or nearly all of yours have a headline
    elif (usual is not None and usual < 0.3) or not (said is not None and said - a > HEADLINE_LEAD):
        headline_text = ""
    e["hide_title"] = True  # the page's own title style stays off too: the headline or nothing
    if headline_text:
        stacked = e.get("layout") == "stacked" and e.get("cam")
        # One headline, at the top (on the seam between face and gameplay when the facecam is on top, as the top
        # gaming clips do), for the opening seconds only: a line across the picture for the whole clip covers it.
        y = round(CAM_SHARE * 100) if stacked else HEADLINE_Y
        texts.insert(0, {"text": headline_text[:200], "start": 0, "end": round(min(b - a, title_for) + HOOK_MAX, 2), "y_percent": y,
                         "size": HEADLINE_SIZE, "color": "#141414", "font": "poppins", "all_caps": True, "outline": 0, "box": True, "headline": True})
    if sound and not e.get("sounds"):
        pick = auto_sound(db, a, b, " ".join(w.text for w in words))
        if pick:
            name, when = pick
            if choice and choice != name:  # the user's pick, landing on the moment itself
                name, when = choice, (when + 1.5 if name == "riser" else when)
            e["sounds"] = [{"name": name, "at": round(edit["start"] + when, 3), "volume": 0.6}]
    e["texts"] = texts[:20]
    peak = peak_moment(db, a, b)
    zoom = not style or style.get("zoom_rate", 1) >= 0.3  # your clips punch in on the moment (or Vyral's default)
    if peak is not None and zoom and not e.get("punch"):  # a subtle push in on the moment itself, never the whole clip
        e["punch"] = [round(edit["start"] + peak - 0.15, 3), round(edit["start"] + min(b, peak + 1.4), 3)]
    if hook and not e.get("hook"):
        sec = style["hook_seconds"] if style and style["hook_seconds"] else 0
        h = pick_hook(db, words, a, b, (sec - 0.5, sec, sec + 0.5) if sec else (2.5, 3.0, 4.0))
        if h and (not max_s or b - a + h[1] - h[0] <= max_s):
            e["hook"] = [round(edit["start"] + h[0], 3), round(edit["start"] + h[1], 3)]
    for x in e["texts"]:
        if x.get("headline"):  # the hook plays first, so the headline stays through it and a few seconds more
            x["end"] = round(min(b - a, title_for) + ((e["hook"][1] - e["hook"][0]) if e.get("hook") else 0), 2)
    e["preedited"], e["preedit_version"] = True, VERSION
    return e

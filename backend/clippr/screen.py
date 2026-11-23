"""The clip screener, and what it learns from your reviews.

A clip only goes to review when it's watchable on its own. What short-form clip pages and the platforms' own
creator guidance agree on, and what the clips that did well for you had in common:
- Long enough to set up the moment: at least 25 seconds. Under that there's rarely time for the setup, so the
  payoff means nothing to someone who wasn't watching the stream.
- Something is said. A clip that's only laughing, screaming or "bro" with no words around it has no context. A
  viewer scrolling past doesn't know why it's funny and swipes in the first seconds.
- Setup before the payoff: words in the first half of the clip, so the viewer learns what's going on before the
  big moment.
Clips that fail are held back from review and from Muse, with the reason, and stay in Ready to Upload.

Learning: what you tell Muse when you reject a clip ("too short", "boring", "no context", "just screaming") moves
these limits a step at a time, and the viral pre-edit cuts the next clips to them. Every change is listed in
Settings with the note that caused it, and Reset puts everything back.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from .models import Setting

KEY = "learned"
DEFAULTS = {"min_seconds": 25.0, "max_seconds": 60.0, "min_words": 25, "setup_words": 8, "min_score": 0}
LIMITS = {"min_seconds": (25.0, 45.0), "max_seconds": (35.0, 90.0), "min_words": (15, 80), "setup_words": (4, 30), "min_score": (0, 80)}

# Sounds that carry no context: laughing, screaming, filler.
NOISE = re.compile(r"^(?:a+h+|a+|o+h+|o+|u+h+|u+m+|h+m+|ha(?:ha)*h?|he(?:he)+|lol|lmao|lmfao|bro|bruh|yo+|what|no+|yes+|yeah|yea|"
                   r"ok|okay|wow|w+o+a+h*|oh my god|omg|dude|man|like|wait|stop|go|ay+|eh+|huh)$", re.I)

# What a review note means, and the step it moves. Notes are matched loosely, in your own words.
RULES = [
    (re.compile(r"\b(too short|short|longer|more setup|cut off|ends? too (soon|early))\b", re.I), {"min_seconds": 3.0, "setup_words": 2}),
    (re.compile(r"\b(too long|long|drag|slow|shorter)\b", re.I), {"max_seconds": -5.0}),
    (re.compile(r"\b(boring|not funny|unfunny|mid|dry|nothing happens|lame|meh|weak|dead)\b", re.I), {"min_words": 3, "min_score": 3}),
    (re.compile(r"\b(no context|context|random|confusing|makes? no sense|what'?s happening|no setup|don'?t get it)\b", re.I),
     {"setup_words": 3, "min_words": 3}),
    (re.compile(r"\b(just (laughing|screaming|yelling)|laughing|screaming|yelling|noise)\b", re.I), {"min_words": 5}),
]


def learned(s: Session) -> dict:
    row = s.get(Setting, KEY)
    v = dict(row.value) if row else {}
    return {**DEFAULTS, **{k: v[k] for k in DEFAULTS if k in v}, "history": v.get("history", [])}


def learn(s: Session, note: str, clip_id: int | None = None) -> dict:
    """Move the limits for a review note; returns what changed (empty if the note didn't say anything usable)."""
    cur = learned(s)
    changes: dict = {}
    for pattern, steps in RULES:
        if pattern.search(note or ""):
            for k, step in steps.items():
                changes[k] = changes.get(k, 0) + step
    moved = {}
    for k, step in changes.items():
        lo, hi = LIMITS[k]
        new = type(DEFAULTS[k])(min(hi, max(lo, cur[k] + step)))
        if new != cur[k]:
            moved[k] = [cur[k], new]
            cur[k] = new
    if moved:
        cur["history"] = (cur["history"] + [{"at": datetime.now(timezone.utc).isoformat(), "note": note[:200], "clip_id": clip_id,
                                             "changed": moved}])[-50:]
        row = s.get(Setting, KEY)
        value = {k: cur[k] for k in (*DEFAULTS, "history")}
        if row:
            row.value = value
        else:
            s.add(Setting(key=KEY, value=value))
    return moved


def reset(s: Session) -> None:
    row = s.get(Setting, KEY)
    if row:
        s.delete(row)


def meaningful(words: list[str]) -> int:
    return sum(1 for w in words if (t := re.sub(r"[^\w']", "", w)) and not NOISE.match(t))


def check(words: list[tuple[float, float, str]], length: float, limits: dict) -> dict:
    """words: (start, end, text) in finished-clip seconds; length: the finished clip in seconds."""
    reasons = []
    if length < limits["min_seconds"] - 0.5:
        reasons.append(f"Too short: {length:.0f} s (at least {limits['min_seconds']:.0f} s, so the moment has its setup)")
    said = meaningful([w for _, _, w in words])
    if said < limits["min_words"]:
        reasons.append(f"Little is said ({said} words besides laughing, yelling and filler): no context for someone who wasn't watching")
    setup = meaningful([w for a, _, w in words if a < length / 2])
    if said >= limits["min_words"] and setup < limits["setup_words"]:
        reasons.append(f"No setup: only {setup} words before the halfway point, so the payoff comes out of nowhere")
    return {"pass": not reasons, "reasons": reasons, "words": said, "length": round(length, 1)}

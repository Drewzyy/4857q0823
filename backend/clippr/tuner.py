"""Vyral improving itself from how its own clips do once posted.

Every new clip is cut with a set of choices (its "trial"): whether it opens on the climax (hook), whether it has a
headline, a sound effect, a zoom-in on the moment, and its length (your usual, 10 s shorter or 10 s longer). Most
clips use the best choices so far; about one in four tries something else on one of them, so Vyral keeps finding
out instead of guessing. The choices are kept with the clip.

Every 6 hours the clips that have been posted for at least 12 hours are scored: views an hour, compared with what's
normal for the page they're on (so a big page doesn't make its clips look better). For each choice, the options are
compared. Once one has at least 6 posts behind it, as do the others, and beats them by a clear margin (a quarter
more views an hour or so), it becomes the default for new clips. If it later stops winning, it stops being the
default. Settings shows every comparison with its numbers, and Reset starts over.
"""
from __future__ import annotations

import math
import random
from datetime import datetime, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import Clip, ClipOutput, MetricSnapshot, Setting

KEY = "tuned"
EXPLORE = 0.25  # share of clips that try something other than the best so far
MIN_POSTS = 6  # posts each option needs before it can be compared
MARGIN = 0.1  # log10 views an hour: about 26% more
KNOBS: dict[str, tuple] = {"hook": (True, False), "headline": (True, False), "sfx": (True, False), "zoom": (True, False),
                           "length": (0, -10, 10)}
NAMES = {"hook": "Climax first (hook)", "headline": "Headline on the video", "sfx": "Sound effect", "zoom": "Zoom-in on the moment",
         "length": "Length vs your usual (s)"}


def state(s: Session) -> dict:
    r = s.get(Setting, KEY)
    return dict(r.value) if r else {"best": {}, "results": {}, "updated": None}


def pick(s: Session, rng: random.Random | None = None) -> dict:
    """What a new clip must do: the best so far for each choice that's been decided (the rest are left to your
    style and Vyral's usual), except that sometimes one choice tries another option. The clip then records what it
    actually got (preedit.apply), which is what's compared."""
    rng = rng or random.Random()
    best = state(s).get("best", {})
    force = {k: best[k] for k in KNOBS if k in best}
    if rng.random() < EXPLORE:
        knob = rng.choice(list(KNOBS))
        force[knob] = rng.choice([o for o in KNOBS[knob] if o != best.get(knob, KNOBS[knob][0] if knob == "length" else None)])
        force["exploring"] = knob
    return force


def _scores(s: Session, since: datetime) -> list[tuple[dict, float]]:
    """(the clip's choices, how it did against its page's normal) for each post up long enough to judge."""
    now = datetime.now(timezone.utc)
    rows = []
    for o in s.scalars(select(ClipOutput).where(ClipOutput.status == "uploaded", ClipOutput.uploaded_at.is_not(None),
                                                ClipOutput.uploaded_at >= since, ClipOutput.uploaded_at <= now - timedelta(hours=12))).unique():
        snap = s.scalar(select(MetricSnapshot).where(MetricSnapshot.output_id == o.id, MetricSnapshot.views.is_not(None))
                        .order_by(MetricSnapshot.ts.desc()).limit(1))
        clip = s.get(Clip, o.clip_id)
        if not snap or not clip:
            continue
        hours = max(1.0, (now - o.uploaded_at).total_seconds() / 3600)
        rows.append((o.destination_id, (clip.edit or {}).get("trial") or {}, math.log10(1 + snap.views / hours)))
    by_page: dict = {}
    for page, _, v in rows:
        by_page.setdefault(page, []).append(v)
    normal = {p: sorted(v)[len(v) // 2] for p, v in by_page.items()}
    return [(trial, v - normal[page]) for page, trial, v in rows]


def learn(s: Session) -> dict:
    """Compare the options for each choice on the last 60 days of posts and keep the ones that clearly do better."""
    scored = _scores(s, datetime.now(timezone.utc) - timedelta(days=60))
    st = state(s)
    best, results = dict(st.get("best", {})), {}
    for knob, options in KNOBS.items():
        groups = {str(o): [v for t, v in scored if knob in t and t[knob] == o] for o in options}
        results[knob] = {o: {"posts": len(v), "lift": round(sum(v) / len(v), 3) if v else None} for o, v in groups.items()}
        ready = {o: sum(v) / len(v) for o, v in groups.items() if len(v) >= MIN_POSTS}
        if len(ready) >= 2:
            top, top_v = max(ready.items(), key=lambda kv: kv[1])
            rest = max(v for o, v in ready.items() if o != top)
            value = next(o for o in options if str(o) == top)
            if top_v - rest >= MARGIN:
                best[knob] = value
            elif best.get(knob) is not None and str(best[knob]) != top:
                best.pop(knob)  # the old winner no longer wins clearly: back to testing it
    value = {"best": best, "results": results, "posts": len(scored), "updated": datetime.now(timezone.utc).isoformat(timespec="minutes")}
    r = s.get(Setting, KEY)
    if r:
        r.value = value
    else:
        s.add(Setting(key=KEY, value=value))
    return value


def reset(s: Session) -> None:
    r = s.get(Setting, KEY)
    if r:
        s.delete(r)

"""What kind of clip this is: gaming, podcast, IRL or just chatting, worked out from the clip itself so it goes to
the right pages (a gaming clip to the gaming page, a podcast clip to the podcast page) and is graded for what it is.

Signals, all measured on this computer from things Vyral already reads:
- the stream's category on Twitch or Kick (a game's name, "Just Chatting", "Talk Shows & Podcasts", "IRL");
- faces in a dozen frames (facecam.sample): a small face fixed in a corner is a streamer over a game; two or more
  steady faces at a table is a podcast; one big face is someone talking to camera;
- how much the picture moves (grade.picture): games and IRL move a lot, podcasts and chatting barely;
- how much is said (words a second): podcasts and chatting are nearly all talk.
The category, when there is one, is the strongest signal; the picture decides when there isn't one or it's vague.
"""
from __future__ import annotations

import re

import numpy as np

from .describe import NOT_GAMES

KINDS = {"gaming": "gaming", "podcast": "podcast", "irl": "regular", "chatting": "regular"}  # detected -> page kind
PODCAST_CATEGORY = re.compile(r"podcast|talk show", re.I)


def classify(*, game: str, faces: tuple | None, motion: np.ndarray | None, words: int, dur: float) -> dict:
    """{"kind": gaming | podcast | irl | chatting, "page_kind": regular | gaming | podcast, "confidence": 0..1,
    "why": [reasons]}. faces: facecam.sample()'s (frames, size)."""
    from .media.facecam import pick
    why: list[str] = []
    frames, size = faces if faces else ([], None)
    corner_cam = bool(frames and size and pick(frames, *size))
    w = size[0] if size else 1
    big = [max(f[2] for f in fs) / w for fs in frames if fs]  # the biggest face in each frame, as a share of the width
    many = [sum(1 for f in fs if f[2] / w > 0.06) for fs in frames]
    seen = len(big) / len(frames) if frames else 0.0
    two_plus = (sum(1 for n in many if n >= 2) / len(frames)) if frames else 0.0
    moving = float(np.mean(motion)) if motion is not None and len(motion) else None
    talk = words / max(dur, 1.0)
    signals = {"face_seen": round(seen, 2), "face_size": round(float(np.median(big)), 3) if big else 0.0,
               "corner_cam": corner_cam, "motion": round(moving, 3) if moving is not None else None, "talk": round(talk, 2)}

    def _out(kind: str, confidence: float, why: list[str]) -> dict:
        return {"kind": kind, "page_kind": KINDS[kind], "confidence": round(confidence, 2), "why": why, "signals": signals}

    category = (game or "").strip()
    if category and PODCAST_CATEGORY.search(category):
        return _out("podcast", 0.95, [f"streamed under {category}"])
    if category and category.lower() not in NOT_GAMES and category.lower() != "irl":
        return _out("gaming", 0.9 if corner_cam or (moving or 0) > 0.04 else 0.8, [f"playing {category}"])
    if category.lower() == "irl":
        return _out("irl", 0.85, ["streamed under IRL"])

    # No category (or Just Chatting): the picture decides.
    if corner_cam and (moving or 0) > 0.03:
        why.append("a facecam in the corner over a moving picture")
        return _out("gaming", 0.7, why)
    if two_plus >= 0.5 and (moving is None or moving < 0.04) and talk > 1.2:
        why.append("two or more people on camera, mostly talking, little movement")
        return _out("podcast", 0.75, why)
    if (moving or 0) > 0.06 and not corner_cam:
        why.append("the camera moves a lot, no facecam: out and about")
        return _out("irl", 0.65, why)
    if seen >= 0.5 and big and float(np.median(big)) > 0.15:
        why.append("one person close to the camera, talking")
        return _out("chatting", 0.7, why)
    return _out("chatting", 0.4, why or ["nothing stood out; treated as a regular clip"])


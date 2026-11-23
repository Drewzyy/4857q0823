"""Review, approval and publishing: the one place the rules live, used by the app and by Muse (mcp.py).

The chain for each page's video: made -> safety check (safety.py) -> virality grade -> review -> approved or
rejected -> Muse posts it (get_posting_package) -> Muse reports the link (mark_posted).
- A quarantined clip (safety fail), a streamer without clip permission, or a grade under Settings' minimum never
  reaches review, whatever page it's moved to or however it's re-rendered.
- Approving needs whoever approves to have watched it (the picture isn't machine-checked: see safety.py).
- Vyral posts nothing itself. A page's Auto-post setting only tells Muse it may post an approved clip without
  asking you first: it needs 5 reviewed posts on the page first, a clip that passed safety outright, the daily
  cap not reached and the kill switch off.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session, object_session

from . import screen
from .api.system import load_settings
from .audit import audit
from .fetch import FetchError
from .models import Clip, ClipOutput, DestinationAccount

UNLOCK_AFTER = 5  # reviewed posts on a page before its Auto-post can be turned on


class PostingError(Exception):
    pass


def held_back(clip: Clip, min_virality: int) -> str | None:
    """Why this clip can't be reviewed or posted, or None if it can."""
    if clip.creator and not clip.creator.clip_permission:
        return "You haven't confirmed permission to clip this streamer"
    safe = clip.safety or {}
    if safe.get("status") == "fail":
        return "Quarantined by the safety check: " + "; ".join(f["reason"] for f in safe.get("flags", []) if f["level"] == "fail")
    if not safe.get("status"):
        return "The safety check hasn't run yet"
    score = (clip.grade or {}).get("score")
    if score is None:
        return "Not graded yet"
    scr = (clip.grade or {}).get("screen")
    if scr and not scr.get("pass"):
        return "Held back by the screener: " + "; ".join(scr.get("reasons", []))
    s = object_session(clip)
    taught = screen.learned(s)["min_score"] if s else 0
    if score < max(min_virality, taught):
        return f"Virality score {score} is under the minimum of {max(min_virality, taught)}" + \
            (" (Settings)" if min_virality >= taught else " (raised by your reviews)")
    return None


def reviewed_posts(s: Session, dest_id: int) -> int:
    """Videos on this page that were reviewed, approved and were posted."""
    return s.scalar(select(func.count()).select_from(ClipOutput).where(
        ClipOutput.destination_id == dest_id, ClipOutput.review == "approved", ClipOutput.reviewed_by != "auto",
        ClipOutput.status == "uploaded")) or 0


def _output(s: Session, oid: int) -> tuple[ClipOutput, Clip]:
    o = s.get(ClipOutput, oid)
    if not o or o.status in ("expired", "withdrawn"):
        raise PostingError("No such video, or it has expired or its streamer is turned off")
    return o, s.get(Clip, o.clip_id)


def approve(s: Session, oid: int, actor: str, *, watched: bool, caption: str | None = None,
            scheduled_at: datetime | None = None) -> ClipOutput:
    o, clip = _output(s, oid)
    why = held_back(clip, load_settings(s).posting.min_virality)
    if why:
        raise PostingError(why)
    if not watched:
        raise PostingError("Watch the video before approving: nudity, gore and weapons on screen aren't machine-checked")
    if o.render_state == "rendering":
        raise PostingError("It's re-rendering; approve the new version when it's ready")
    if (o.quality or {}).get("status") == "fail":
        raise PostingError("The video didn't pass the quality check: " + "; ".join(o.quality.get("problems", [])))
    if caption is not None:
        o.description = caption.strip()[:2200]
    o.review, o.review_note, o.reviewed_by, o.scheduled_at = "approved", "", actor, scheduled_at
    audit(s, "output.approved", "clip_output", oid, {"by": actor, "clip": clip.id, "scheduled": bool(scheduled_at)})
    return o


def reject(s: Session, oid: int, actor: str, reason: str, teach: bool = True) -> ClipOutput:
    o, clip = _output(s, oid)
    o.review, o.review_note, o.reviewed_by = "rejected", reason.strip()[:500], actor
    learned = screen.learn(s, o.review_note, clip.id) if teach else {}  # "too short", "boring", "no context": the next clips are cut to it
    audit(s, "output.rejected", "clip_output", oid, {"by": actor, "clip": clip.id, "reason": o.review_note, "learned": learned})
    return o


def can_turn_on_auto_post(s: Session, dest: DestinationAccount) -> str | None:
    n = reviewed_posts(s, dest.id)
    return None if n >= UNLOCK_AFTER else f"Auto-post unlocks after {UNLOCK_AFTER} reviewed posts on this page ({n} so far)"


def package(s: Session, oid: int) -> dict:
    """Everything needed to post an approved video by hand or through Muse."""
    o, clip = _output(s, oid)
    if o.review != "approved":
        raise PostingError("Approve it first")
    if not o.file_path or not Path(o.file_path).exists():
        raise PostingError("The video file is gone (expired or deleted)")
    d = o.destination
    from .media.ffmpeg import probe
    dur = probe(Path(o.file_path)).duration
    from .dropbox import status_for
    box = status_for(s, o.file_path)
    # Posts too close together on one page flop: the earliest time this one should go up (now, or after the last one).
    gap = timedelta(minutes=load_settings(s).posting.spacing_minutes)
    last = s.scalar(select(func.max(ClipOutput.uploaded_at)).where(ClipOutput.destination_id == o.destination_id,
                                                                   ClipOutput.status == "uploaded")) if o.destination_id else None
    post_after = max(datetime.now(timezone.utc), last + gap) if last else datetime.now(timezone.utc)
    return {"post_after": post_after.isoformat(timespec="minutes"), "output_id": o.id, "clip_id": clip.id, "video_path": str(Path(o.file_path).resolve()), "caption": o.description,
            "title": o.title, "platform": o.platform, "destination": {"id": d.id, "handle": d.handle, "name": d.display_name} if d else None,
            "width": o.width, "height": o.height, "aspect_ratio": f"{o.width}:{o.height}" if o.width else None,
            "duration": round(dur or 0, 2), "scheduled_at": o.scheduled_at.isoformat() if o.scheduled_at else None,
            "dropbox_status": box["status"] if box else None, "dropbox_path": box["path"] if box and box["status"] == "uploaded" else None}


GONE = re.compile(r"not available|unavailable|removed|doesn'?t exist|does not exist|not found|404|private|deleted|no video", re.I)
CHECKABLE = ("tiktok", "youtube")  # public posts Vyral can open without logging in


def _who(x: str) -> str:
    return re.sub(r"[^a-z0-9]", "", x.lower())


def check_post(s: Session, fetcher, o: ClipOutput, url: str) -> dict:
    """Opens the post link and checks it's a real, live post on this page, before it counts as posted.
    TikTok and YouTube are checked outright: a link that doesn't open, or a post on another account, is refused.
    Instagram, Facebook and X need a login to read, so their links are kept but marked unverified."""
    url = url.strip()
    when = datetime.now(timezone.utc).isoformat()
    base = url.split("?")[0].rstrip("/")
    other = s.scalar(select(ClipOutput).where(ClipOutput.post_url.like(f"{base}%"), ClipOutput.id != o.id).limit(1))
    if other:
        return {"status": "failed", "url": url, "at": when, "reason": f"That post is already recorded for clip {other.clip_id}"}
    try:
        p = fetcher.post_details(url)
    except FetchError as e:
        if o.platform in CHECKABLE and GONE.search(str(e)):
            return {"status": "failed", "url": url, "at": when, "reason": f"That link doesn't open a live post ({str(e)[:160]})"}
        why = "couldn't be opened right now; checked again later" if o.platform in CHECKABLE else \
            f"{o.platform.title()} posts can't be opened without logging in"
        return {"status": "unverified", "url": url, "at": when, "reason": why}
    handle = _who((o.destination.handle if o.destination else "") or "")
    names = {_who(x) for x in p.channels if x}
    if handle and names and handle not in names:
        return {"status": "failed", "url": url, "at": when,
                "reason": f"That post is on {', '.join(sorted(x for x in p.channels if x)[:2])}, not this page (@{handle})"}
    return {"status": "verified", "url": url, "at": when, "posted_by": p.channels[0] if p.channels else None,
            "post_caption": (p.title or "")[:200], "posted_at": p.posted_at.isoformat() if p.posted_at else None}

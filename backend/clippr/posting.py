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

from datetime import datetime
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .api.system import load_settings
from .audit import audit
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
    if score < min_virality:
        return f"Virality score {score} is under the minimum of {min_virality} (Settings)"
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


def reject(s: Session, oid: int, actor: str, reason: str) -> ClipOutput:
    o, clip = _output(s, oid)
    o.review, o.review_note, o.reviewed_by = "rejected", reason.strip()[:500], actor
    audit(s, "output.rejected", "clip_output", oid, {"by": actor, "clip": clip.id, "reason": o.review_note})
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
    return {"output_id": o.id, "clip_id": clip.id, "video_path": str(Path(o.file_path).resolve()), "caption": o.description,
            "title": o.title, "platform": o.platform, "destination": {"id": d.id, "handle": d.handle, "name": d.display_name} if d else None,
            "width": o.width, "height": o.height, "aspect_ratio": f"{o.width}:{o.height}" if o.width else None,
            "duration": round(dur or 0, 2), "scheduled_at": o.scheduled_at.isoformat() if o.scheduled_at else None,
            "dropbox_status": box["status"] if box else None, "dropbox_path": box["path"] if box and box["status"] == "uploaded" else None}

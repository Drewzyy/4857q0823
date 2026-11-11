"""Analytics for clips you uploaded: paste the post link, Vyral tracks its public numbers."""
from __future__ import annotations

import re
from collections import defaultdict
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..audit import audit
from ..models import Clip, ClipOutput, Job, MetricSnapshot, ReferenceVideo
from .deps import ApiError, ctx, db, get_or_404

router = APIRouter()
AUTO_PLATFORMS = ("tiktok", "youtube")  # public numbers readable without logging in
HOSTS = {"tiktok": r"(tiktok\.com)", "youtube": r"(youtube\.com|youtu\.be)", "instagram": r"(instagram\.com)", "facebook": r"(facebook\.com|fb\.watch)"}


class PostIn(BaseModel):
    post_url: str = Field(min_length=8, max_length=500)


@router.put("/outputs/{oid}/post")
def set_post_link(oid: int, body: PostIn, c=Depends(ctx), s: Session = Depends(db)):
    o = get_or_404(s, ClipOutput, oid, "Clip")
    url = body.post_url.strip()
    if not re.match(rf"^https://([\w-]+\.)?{HOSTS.get(o.platform, '')}/", url):
        raise ApiError(422, "invalid_input", f"That isn't a {o.platform.title()} link. Paste the link to the post you uploaded.")
    o.post_url = url
    if o.status != "uploaded":
        o.status, o.uploaded_at = "uploaded", datetime.now(timezone.utc)
    audit(s, "clip.post_linked", "output", oid, {"platform": o.platform})
    # Copying this link to paste here may have been picked up as a new clip to make: undo that.
    base = url.split("?")[0].rstrip("/")
    for r in s.scalars(select(ReferenceVideo).where(ReferenceVideo.url.like(f"{base}%"), ReferenceVideo.source_id.is_(None))):
        for job in s.scalars(select(Job).where(Job.kind == "clip.build", Job.status.in_(("queued", "running")))):
            if job.payload.get("reference_id") == r.id:
                job.status = "cancelled"
        r.status, r.status_detail = "removed", "Your own post"
    if o.platform in AUTO_PLATFORMS:
        c.jobs.enqueue("metrics.fetch", {"output_id": oid}, max_attempts=2, session=s)
    return {"post_url": url, "auto": o.platform in AUTO_PLATFORMS}


class ManualMetrics(BaseModel):
    views: int | None = Field(None, ge=0)
    likes: int | None = Field(None, ge=0)
    comments: int | None = Field(None, ge=0)
    shares: int | None = Field(None, ge=0)


@router.post("/outputs/{oid}/metrics")
def add_manual_metrics(oid: int, body: ManualMetrics, s: Session = Depends(db)):
    """For platforms Vyral can't read without your login (Instagram, Facebook)."""
    get_or_404(s, ClipOutput, oid, "Clip")
    if all(v is None for v in body.model_dump().values()):
        raise ApiError(422, "validation", "Enter at least one number")
    s.add(MetricSnapshot(output_id=oid, source="manual", **body.model_dump()))
    return {"ok": True}


def latest_snapshots(s: Session, ids: list[int]) -> dict[int, MetricSnapshot]:
    out: dict[int, MetricSnapshot] = {}
    if ids:
        for m in s.scalars(select(MetricSnapshot).where(MetricSnapshot.output_id.in_(ids)).order_by(MetricSnapshot.ts)):
            out[m.output_id] = m  # later rows overwrite earlier ones
    return out


def _sum(rows, field):
    vals = [getattr(r, field) for r in rows if getattr(r, field) is not None]
    return sum(vals) if vals else None


@router.get("/analytics")
def analytics(days: int = 30, platform: str | None = None, creator_id: int | None = None, destination_id: int | None = None,
              s: Session = Depends(db)):
    since = datetime.now(timezone.utc) - timedelta(days=max(1, min(days, 3650)))
    clips_made = len([c for c in s.scalars(select(Clip).where(Clip.created_at >= since)).unique()
                      if not creator_id or c.creator_id == creator_id])
    q = select(ClipOutput).where(ClipOutput.status.in_(("uploaded", "expired")), ClipOutput.uploaded_at.is_not(None), ClipOutput.uploaded_at >= since)
    if platform:
        q = q.where(ClipOutput.platform == platform)
    if destination_id:
        q = q.where(ClipOutput.destination_id == destination_id)
    outputs = [o for o in s.scalars(q).unique()]
    clips = {c.id: c for c in s.scalars(select(Clip).where(Clip.id.in_([o.clip_id for o in outputs]))).unique()} if outputs else {}
    if creator_id:
        outputs = [o for o in outputs if clips.get(o.clip_id) and clips[o.clip_id].creator_id == creator_id]
    snaps = latest_snapshots(s, [o.id for o in outputs])
    tracked = [snaps[o.id] for o in outputs if o.id in snaps]

    def totals(rows):
        views = _sum(rows, "views")
        eng = None
        if views:
            eng = round(((_sum(rows, "likes") or 0) + (_sum(rows, "comments") or 0) + (_sum(rows, "shares") or 0)) / views * 100, 2)
        return {"views": views, "likes": _sum(rows, "likes"), "comments": _sum(rows, "comments"), "shares": _sum(rows, "shares"),
                "engagement_rate": eng, "avg_views": round(views / len(rows)) if views and rows else None}

    def group(keyfn, labelfn):
        buckets: dict = defaultdict(list)
        for o in outputs:
            buckets[keyfn(o)].append(o)
        res = []
        for key, items in buckets.items():
            rows = [snaps[o.id] for o in items if o.id in snaps]
            res.append({"key": key, "label": labelfn(key, items), "posts": len(items), "tracked": len(rows), **totals(rows)})
        return sorted(res, key=lambda r: (r["views"] is None, -(r["views"] or 0)))

    def length_bucket(o):
        d = (clips.get(o.clip_id).source_duration if clips.get(o.clip_id) else None) or 0
        return "Under 20 s" if d < 20 else "20 to 40 s" if d < 40 else "40 to 60 s" if d < 60 else "Over 60 s"

    creator_name = lambda k, items: (clips[items[0].clip_id].creator.name if k and clips[items[0].clip_id].creator else "No streamer")  # noqa: E731
    top = sorted((o for o in outputs if o.id in snaps and snaps[o.id].views is not None), key=lambda o: -snaps[o.id].views)[:10]
    by_day: dict = defaultdict(lambda: {"posts": 0, "views": 0})
    for o in outputs:
        d = o.uploaded_at.astimezone().date().isoformat()
        by_day[d]["posts"] += 1
        if o.id in snaps and snaps[o.id].views is not None:
            by_day[d]["views"] += snaps[o.id].views
    return {
        "range_days": days, "clips_made": clips_made, "uploaded": len(outputs), "tracked": len(tracked),
        "untracked": [{"output_id": o.id, "title": o.title, "platform": o.platform, "has_link": bool(o.post_url)}
                      for o in outputs if o.id not in snaps][:20],
        "totals": totals(tracked),
        "by_platform": group(lambda o: o.platform, lambda k, _: k),
        "by_creator": group(lambda o: clips[o.clip_id].creator_id if clips.get(o.clip_id) else None, creator_name),
        "by_destination": group(lambda o: o.destination_id, lambda k, items: items[0].destination.display_name if items[0].destination else "Removed page"),
        "by_length": group(length_bucket, lambda k, _: k),
        "top": [{"output_id": o.id, "title": o.title, "platform": o.platform, "post_url": o.post_url,
                 "destination": o.destination.display_name if o.destination else None,
                 "duration": clips[o.clip_id].source_duration if clips.get(o.clip_id) else None,
                 "uploaded_at": o.uploaded_at.isoformat(), "views": snaps[o.id].views, "likes": snaps[o.id].likes,
                 "comments": snaps[o.id].comments, "shares": snaps[o.id].shares, "updated": snaps[o.id].ts.isoformat()} for o in top],
        "timeline": [{"day": d, **v} for d, v in sorted(by_day.items())],
    }

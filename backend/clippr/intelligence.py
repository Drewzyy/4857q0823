"""Vyral Intelligence: the agents Vyral runs, what each is doing, and what needs the user.

Every agent's work is a job in the persistent queue (jobs.py): retries, cancellation, deduplication and crash
recovery come from there. This module names the agents, describes their live work from the records they touch,
and gathers what's waiting on the user. Nothing here is simulated: an agent with no jobs shows as idle.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import func, select

from .models import ClipOutput, Event, Job, ReferenceVideo, SourceAccount

AGENTS: dict[str, dict[str, Any]] = {
    "monitor": {"name": "Source Monitor", "does": "Checks your source accounts for new posts and top Twitch clips.",
                "kinds": ("monitor.tick", "source.check")},
    "intake": {"name": "Link Intake", "does": "Picks up links you copy, paste in batches or post in your Discord inbox.",
               "kinds": ("intake.link",)},
    "production": {"name": "Video Production", "does": "Finds each moment in the full stream, cuts it in full quality, writes captions and renders every page's version.",
                   "kinds": ("clip.build", "clip.rerender")},
    "analyst": {"name": "Performance Analyst", "does": "Reads the views and engagement of clips you've posted.",
                "kinds": ("metrics.fetch", "metrics.refresh")},
    "notifier": {"name": "Notifications", "does": "Delivers events to your Discord channels.", "kinds": ("notify.discord",)},
    "housekeeping": {"name": "Housekeeping", "does": "Deletes expired clips and old history.", "kinds": ("storage.cleanup",)},
}
AGENT_OF = {kind: key for key, a in AGENTS.items() for kind in a["kinds"]}
QUIET_KINDS = ("monitor.tick",)  # runs every minute; listing each run would bury real work


def _detail(s, j: Job) -> str:
    """What a job is working on, in words, from the record it works on."""
    p = j.payload or {}
    if j.kind == "clip.build" and (r := s.get(ReferenceVideo, p.get("reference_id"))):
        return f"{(r.title or r.url)[:80]}: {r.status_detail}"
    if j.kind == "clip.rerender":
        n = len(p.get("output_ids") or [])
        return f"Re-rendering {n} video{'' if n == 1 else 's'} with your edits"
    if j.kind == "source.check" and (src := s.get(SourceAccount, p.get("source_id"))):
        return f"Checking @{src.username} ({src.platform})"
    if j.kind == "intake.link":
        return f"Opening {p.get('url', 'a link')}"
    if j.kind == "metrics.fetch" and (o := s.get(ClipOutput, p.get("output_id"))):
        return f"Reading numbers for {o.title[:80]}"
    if j.kind == "notify.discord" and (e := s.get(Event, p.get("event_id"))):
        return f"Sending: {e.title[:80]}"
    return j.kind


def _job(s, j: Job) -> dict[str, Any]:
    def iso(d):
        return d.isoformat() if d else None
    return {"id": j.id, "agent": AGENT_OF.get(j.kind, "other"), "kind": j.kind, "status": j.status, "detail": _detail(s, j),
            "error": j.error, "attempts": j.attempts, "created_at": iso(j.created_at), "started_at": iso(j.started_at), "finished_at": iso(j.finished_at)}


def activity(s) -> dict[str, Any]:
    day_ago = datetime.now(timezone.utc) - timedelta(days=1)
    live = list(s.scalars(select(Job).where(Job.status.in_(("running", "queued"))).order_by(Job.created_at)))
    recent = list(s.scalars(select(Job).where(Job.status.in_(("succeeded", "failed", "cancelled")), Job.kind.not_in(QUIET_KINDS))
                            .order_by(Job.finished_at.desc()).limit(25)))
    failed = dict(s.execute(select(Job.kind, func.count()).where(Job.status == "failed", Job.finished_at >= day_ago).group_by(Job.kind)).all())
    done = dict(s.execute(select(Job.kind, func.count()).where(Job.status == "succeeded", Job.finished_at >= day_ago).group_by(Job.kind)).all())
    agents = []
    for key, a in AGENTS.items():
        mine = [j for j in live if AGENT_OF.get(j.kind) == key]
        running = [j for j in mine if j.status == "running" and j.kind not in QUIET_KINDS]
        agents.append({
            "key": key, "name": a["name"], "does": a["does"],
            "state": "working" if running else "waiting" if any(j.kind not in QUIET_KINDS for j in mine) else "idle",
            "running": [_job(s, j) for j in running], "queued": sum(1 for j in mine if j.status == "queued" and j.kind not in QUIET_KINDS),
            "done_24h": sum(done.get(k, 0) for k in a["kinds"] if k not in QUIET_KINDS), "failed_24h": sum(failed.get(k, 0) for k in a["kinds"]),
        })
    return {"agents": agents, "recent": [_job(s, j) for j in recent]}


def needs_you(s) -> list[dict[str, Any]]:
    """Everything waiting on the user, most important first. Each item links to where it's handled."""
    week_ago = datetime.now(timezone.utc) - timedelta(days=7)
    items: list[dict[str, Any]] = []
    ready = s.scalar(select(func.count()).select_from(ClipOutput).where(ClipOutput.status == "ready", ClipOutput.render_state == "ready")) or 0
    if ready:
        items.append({"kind": "upload", "count": ready, "title": f"{ready} video{'' if ready == 1 else 's'} ready to upload", "link": "/ready"})
    for status, title in (("needs_setup", "need setup before they can be clipped"), ("no_match", "weren't found in the streams searched"),
                          ("failed", "failed")):
        n = s.scalar(select(func.count()).select_from(ReferenceVideo).where(ReferenceVideo.status == status, ReferenceVideo.updated_at >= week_ago)) or 0
        if n:
            items.append({"kind": status, "count": n, "title": f"{n} post{'' if n == 1 else 's'} {title}", "link": "/activity"})
    bad_renders = s.scalar(select(func.count()).select_from(ClipOutput).where(ClipOutput.render_state == "failed", ClipOutput.status != "expired")) or 0
    if bad_renders:
        items.append({"kind": "render", "count": bad_renders, "title": f"{bad_renders} re-render{'' if bad_renders == 1 else 's'} failed", "link": "/ready"})
    erroring = s.scalar(select(func.count()).select_from(SourceAccount).where(SourceAccount.last_error.is_not(None), SourceAccount.monitoring == "active")) or 0
    if erroring:
        items.append({"kind": "source", "count": erroring, "title": f"{erroring} source account{'' if erroring == 1 else 's'} can't be checked", "link": "/sources"})
    return items

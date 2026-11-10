"""What's waiting on the user: clips to upload, posts that need setup or weren't found, failed renders and
accounts that can't be checked. Each item links to where it's handled.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from sqlalchemy import func, select

from .models import ClipOutput, ReferenceVideo, SourceAccount


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

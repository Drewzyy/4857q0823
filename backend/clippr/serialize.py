"""Model -> JSON dicts for the API. Never include secrets."""
from __future__ import annotations

from typing import Any

from .fetch import MONITORABLE
from .models import Creator, DestinationAccount, Folder, Job, SourceAccount


def _dt(v):
    return v.isoformat() if v else None


def creator(c: Creator | None) -> dict[str, Any] | None:
    if not c:
        return None
    return {"id": c.id, "name": c.name, "color": c.color, "notes": c.notes,
            "vod_channels": list(c.vod_channels or []), "clip_permission": bool(c.clip_permission),
            "facecam": c.facecam}


def folder(f: Folder | None) -> dict[str, Any] | None:
    return {"id": f.id, "name": f.name} if f else None


def source(s: SourceAccount, page_count: int = 0, creators_by_id: dict | None = None) -> dict[str, Any]:
    from .routing import source_creator_ids

    ids = source_creator_ids(s)
    all_creators = [creator(creators_by_id[i]) for i in ids if creators_by_id and i in creators_by_id] if creators_by_id is not None \
        else ([creator(s.creator)] if s.creator else [])
    return {
        "creators": all_creators,
        "id": s.id, "platform": s.platform, "username": s.username, "display_name": s.display_name,
        "profile_url": s.profile_url, "avatar_url": s.avatar_url, "monitoring": s.monitoring, "notes": s.notes,
        "creator": creator(s.creator), "folder": folder(s.folder),
        "last_synced_at": _dt(s.last_synced_at), "next_check_at": _dt(s.next_check_at), "last_error": s.last_error,
        "watching_supported": s.platform in MONITORABLE, "baseline_done": s.baseline_done,
        "created_at": _dt(s.created_at), "page_count": page_count,
        # Filled in by the accounts list endpoint; None means not counted, not zero.
        "videos_discovered": None, "videos_analyzed": None,
    }


def normalized_settings(raw: dict | None) -> dict:
    """Saved settings from any version: new options get defaults, ones no longer used are dropped."""
    from .schemas import DestinationSettings, lenient

    return lenient(DestinationSettings, raw).model_dump()


def destination(d: DestinationAccount) -> dict[str, Any]:
    return {
        "id": d.id, "platform": d.platform, "external_id": None if d.external_id.startswith(("draft:", "manual:")) else d.external_id,
        "handle": d.handle, "display_name": d.display_name, "avatar_url": d.avatar_url,
        "creator": creator(d.creator), "creator_ids": [int(i) for i in (d.creator_ids or [])] or ([d.creator_id] if d.creator_id else []),
        "settings": normalized_settings(d.settings), "enabled": d.enabled,
        "status": "manual",  # you upload each clip yourself
        "created_at": _dt(d.created_at),
    }


def job(j: Job) -> dict[str, Any]:
    return {
        "id": j.id, "kind": j.kind, "status": j.status, "attempts": j.attempts, "max_attempts": j.max_attempts,
        "error": j.error, "result": j.result, "created_at": _dt(j.created_at), "started_at": _dt(j.started_at),
        "finished_at": _dt(j.finished_at), "run_after": _dt(j.run_after),
    }

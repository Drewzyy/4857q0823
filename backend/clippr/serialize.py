"""Model -> JSON dicts for the API. Never include secrets."""
from __future__ import annotations

from typing import Any

from .models import Connection, Creator, DestinationAccount, Folder, Job, SourceAccount


def _dt(v):
    return v.isoformat() if v else None


def creator(c: Creator | None) -> dict[str, Any] | None:
    if not c:
        return None
    return {"id": c.id, "name": c.name, "color": c.color, "notes": c.notes,
            "vod_channels": list(c.vod_channels or []), "clip_permission": bool(c.clip_permission)}


def folder(f: Folder | None) -> dict[str, Any] | None:
    return {"id": f.id, "name": f.name} if f else None


def connection(c: Connection | None) -> dict[str, Any] | None:
    if not c:
        return None
    return {
        "id": c.id, "platform": c.platform, "display_name": c.display_name, "avatar_url": c.avatar_url,
        "status": c.status, "last_error": c.last_error, "scopes": c.scopes,
        "access_expires_at": _dt(c.access_expires_at), "refresh_expires_at": _dt(c.refresh_expires_at),
        "last_checked_at": _dt(c.last_checked_at), "created_at": _dt(c.created_at),
    }


def source(s: SourceAccount, route_count: int = 0) -> dict[str, Any]:
    return {
        "id": s.id, "platform": s.platform, "username": s.username, "display_name": s.display_name,
        "profile_url": s.profile_url, "avatar_url": s.avatar_url, "monitoring": s.monitoring, "notes": s.notes,
        "creator": creator(s.creator), "folder": folder(s.folder),
        "authorized": s.connection is not None, "connection_status": s.connection.status if s.connection else None,
        "last_synced_at": _dt(s.last_synced_at), "next_check_at": _dt(s.next_check_at), "last_error": s.last_error,
        "watching_supported": s.platform in ("tiktok", "youtube"), "baseline_done": s.baseline_done,
        "created_at": _dt(s.created_at), "route_count": route_count,
        # Filled in by the accounts list endpoint; None means not counted, not zero.
        "videos_discovered": None, "videos_analyzed": None,
    }


def normalized_settings(raw: dict | None) -> dict:
    """Older saved settings get any newly added options filled with defaults."""
    from pydantic import ValidationError

    from .schemas import DestinationSettings

    try:
        return DestinationSettings.model_validate(raw or {}).model_dump()
    except ValidationError:
        return raw or {}


def destination(d: DestinationAccount, route_count: int = 0) -> dict[str, Any]:
    if d.external_id.startswith(("draft:", "manual:")):
        status = "manual"
    elif not d.connection:
        status = "disconnected"
    else:
        status = d.connection.status
    return {
        "id": d.id, "platform": d.platform, "external_id": None if d.external_id.startswith(("draft:", "manual:")) else d.external_id,
        "handle": d.handle, "display_name": d.display_name, "avatar_url": d.avatar_url,
        "creator": creator(d.creator), "settings": normalized_settings(d.settings), "enabled": d.enabled,
        "status": status, "connection_id": d.connection_id, "last_error": d.connection.last_error if d.connection else None,
        "route_count": route_count, "created_at": _dt(d.created_at),
    }


def job(j: Job) -> dict[str, Any]:
    return {
        "id": j.id, "kind": j.kind, "status": j.status, "attempts": j.attempts, "max_attempts": j.max_attempts,
        "error": j.error, "result": j.result, "created_at": _dt(j.created_at), "started_at": _dt(j.started_at),
        "finished_at": _dt(j.finished_at), "run_after": _dt(j.run_after),
    }

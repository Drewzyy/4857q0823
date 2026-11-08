"""Dashboard, settings, jobs, audit log, health."""
from __future__ import annotations

import os
import shutil
from pathlib import Path

from fastapi import APIRouter, Depends, Request
from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import __version__
from .. import serialize as ser
from ..audit import audit
from ..models import AuditLog, Clip, ClipOutput, Connection, Creator, DestinationAccount, FunnelRoute, Job, ReferenceVideo, Setting, SourceAccount
from ..schemas import AppSettings
from .deps import ApiError, ctx, db

router = APIRouter()
SETTINGS_KEY = "app"


def _dir_size(path: Path, limit: int = 200_000) -> int:
    total, n = 0, 0
    for root, _, files in os.walk(path):
        for f in files:
            n += 1
            if n > limit:
                return total
            try:
                total += os.lstat(os.path.join(root, f)).st_size
            except OSError:
                pass
    return total


def _has_ffmpeg() -> bool:
    from ..media.ffmpeg import FFmpegError, ffmpeg_exe

    try:
        return bool(ffmpeg_exe())
    except FFmpegError:
        return False


@router.get("/health")
def health(request: Request, c=Depends(ctx), s: Session = Depends(db)):
    s.execute(select(1))
    return {"ok": True, "version": __version__, "secret_backend": c.secrets.name,
            "worker_running": c.config.run_worker, "desktop_mode": c.config.desktop_mode, "ui_served": bool(getattr(request.app.state, "ui_served", False)), "ffmpeg": _has_ffmpeg()}


@router.get("/dashboard")
def dashboard(c=Depends(ctx), s: Session = Depends(db)):
    count = lambda stmt: s.scalar(stmt) or 0  # noqa: E731
    jobs_by_status = dict(s.execute(select(Job.status, func.count()).where(Job.kind != "monitor.tick").group_by(Job.status)).all())
    disk = shutil.disk_usage(c.config.data_dir)
    from datetime import datetime, timedelta, timezone

    week_ago = datetime.now(timezone.utc) - timedelta(days=7)
    real_dests = select(func.count()).select_from(DestinationAccount).where(~DestinationAccount.external_id.like("draft:%"))
    return {
        "accounts": {
            "sources_total": count(select(func.count()).select_from(SourceAccount)),
            "sources_monitoring": count(select(func.count()).select_from(SourceAccount).where(SourceAccount.monitoring == "active")),
            "sources_authorized": count(select(func.count()).select_from(SourceAccount).where(SourceAccount.connection_id.is_not(None))),
            "destinations_total": count(select(func.count()).select_from(DestinationAccount)),
            "destinations_connected": count(real_dests.where(DestinationAccount.connection_id.is_not(None))),
            "creators": count(select(func.count()).select_from(Creator)),
            "routes": count(select(func.count()).select_from(FunnelRoute).where(FunnelRoute.enabled.is_(True))),
        },
        "connections": [ser.connection(x) for x in s.scalars(select(Connection).order_by(Connection.platform))],
        "platforms": [{"key": p["key"], "label": p["label"], "configured": p["configured"]} for p in c.connections.platform_status()],
        "pipeline": {
            "posts_detected": count(select(func.count()).select_from(ReferenceVideo).where(ReferenceVideo.status != "baseline")),
            "in_progress": count(select(func.count()).select_from(ReferenceVideo).where(ReferenceVideo.status.in_(("new", "processing")))),
            "needs_attention": count(select(func.count()).select_from(ReferenceVideo).where(
                ReferenceVideo.status.in_(("needs_setup", "no_match", "failed")), ReferenceVideo.updated_at >= week_ago)),
            "ready_to_upload": count(select(func.count()).select_from(ClipOutput).where(ClipOutput.status == "ready")),
            "uploaded": count(select(func.count()).select_from(ClipOutput).where(ClipOutput.status == "uploaded")),
            "clips_made": count(select(func.count()).select_from(Clip)),
        },
        "monitoring": {
            "enabled": load_settings(s).monitoring.enabled,
            "interval_minutes": load_settings(s).monitoring.interval_minutes,
            "watching": count(select(func.count()).select_from(SourceAccount).where(
                SourceAccount.monitoring == "active", SourceAccount.platform.in_(("tiktok", "youtube")))),
            "last_check": max((x for x in s.scalars(select(SourceAccount.last_synced_at)) if x), default=None),
            "errors": count(select(func.count()).select_from(SourceAccount).where(SourceAccount.last_error.is_not(None))),
            "retention_days": load_settings(s).storage.retention_days,
        },
        "jobs": {"by_status": jobs_by_status,
                 "recent": [ser.job(j) for j in s.scalars(select(Job).where(Job.kind != "monitor.tick").order_by(Job.created_at.desc()).limit(6))]},
        "storage": {"data_dir": str(c.config.data_dir), "used_bytes": _dir_size(c.config.data_dir),
                    "disk_free_bytes": disk.free, "disk_total_bytes": disk.total},
        "secret_backend": c.secrets.name,
    }


def load_settings(s: Session) -> AppSettings:
    row = s.get(Setting, SETTINGS_KEY)
    try:
        return AppSettings.model_validate(row.value) if row else AppSettings()
    except ValidationError:
        return AppSettings()


@router.get("/settings")
def get_settings(s: Session = Depends(db)):
    return load_settings(s).model_dump()


@router.put("/settings")
def put_settings(body: dict, s: Session = Depends(db)):
    try:
        merged = load_settings(s).model_dump()
        for section, values in body.items():
            if isinstance(values, dict) and isinstance(merged.get(section), dict):
                merged[section].update(values)
            else:
                merged[section] = values
        new = AppSettings.model_validate(merged)
    except ValidationError as e:
        first = e.errors()[0]
        raise ApiError(422, "validation", f"{'.'.join(str(x) for x in first['loc'])}: {first['msg']}")
    row = s.get(Setting, SETTINGS_KEY)
    if row:
        row.value = new.model_dump()
    else:
        s.add(Setting(key=SETTINGS_KEY, value=new.model_dump()))
    audit(s, "settings.updated", "settings", "", {"sections": list(body.keys())})
    return new.model_dump()


@router.get("/jobs")
def list_jobs(status: str | None = None, limit: int = 50, s: Session = Depends(db)):
    stmt = select(Job).order_by(Job.created_at.desc()).limit(min(max(limit, 1), 200))
    if status:
        stmt = stmt.where(Job.status == status)
    return [ser.job(j) for j in s.scalars(stmt)]


@router.post("/jobs/{jid}/cancel")
def cancel_job(jid: int, c=Depends(ctx)):
    if not c.jobs.cancel(jid):
        raise ApiError(409, "invalid_state", "Only queued or running jobs can be cancelled")
    return {"ok": True}


@router.post("/jobs/{jid}/retry")
def retry_job(jid: int, c=Depends(ctx)):
    if not c.jobs.retry(jid):
        raise ApiError(409, "invalid_state", "Only failed or cancelled jobs can be retried")
    return {"ok": True}


@router.get("/audit")
def audit_log(limit: int = 100, s: Session = Depends(db)):
    rows = s.scalars(select(AuditLog).order_by(AuditLog.id.desc()).limit(min(max(limit, 1), 500)))
    return [{"id": a.id, "ts": a.ts.isoformat(), "action": a.action, "entity": a.entity, "entity_id": a.entity_id, "details": a.details} for a in rows]

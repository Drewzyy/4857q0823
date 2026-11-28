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
from ..models import AuditLog, Clip, ClipOutput, Creator, DestinationAccount, Job, ReferenceVideo, Setting, SourceAccount
from ..fetch import MONITORABLE
from ..schemas import AppSettings, lenient
from .deps import ApiError, ctx, db

router = APIRouter()
SETTINGS_KEY = "app"


_SIZE_CACHE: dict[str, tuple[float, int]] = {}


def _dir_size(path: Path, limit: int = 200_000, max_age: float = 120) -> int:
    """Disk used by the data folder. Walking every file is slow, and the dashboard asks every few seconds: the
    answer is kept for two minutes."""
    import time
    hit = _SIZE_CACHE.get(str(path))
    if hit and time.monotonic() - hit[0] < max_age:
        return hit[1]
    total = _walk_size(path, limit)
    _SIZE_CACHE[str(path)] = (time.monotonic(), total)
    return total


def _walk_size(path: Path, limit: int) -> int:
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
    disk = shutil.disk_usage(c.config.data_dir)
    from datetime import datetime, timedelta, timezone

    week_ago = datetime.now(timezone.utc) - timedelta(days=7)
    return {
        "accounts": {
            "sources_total": count(select(func.count()).select_from(SourceAccount)),
            "sources_monitoring": count(select(func.count()).select_from(SourceAccount).where(SourceAccount.monitoring == "active")),
            "destinations_total": count(select(func.count()).select_from(DestinationAccount)),
            "creators": count(select(func.count()).select_from(Creator)),
        },
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
                SourceAccount.monitoring == "active", SourceAccount.platform.in_(MONITORABLE))),
            "last_check": max((x for x in s.scalars(select(SourceAccount.last_synced_at)) if x), default=None),
            "errors": count(select(func.count()).select_from(SourceAccount).where(SourceAccount.last_error.is_not(None))),
            "retention_days": load_settings(s).storage.retention_days,
        },
        "storage": {"data_dir": str(c.config.data_dir), "used_bytes": _dir_size(c.config.data_dir),
                    "disk_free_bytes": disk.free, "disk_total_bytes": disk.total},
        "secret_backend": c.secrets.name,
    }


def load_settings(s: Session) -> AppSettings:
    row = s.get(Setting, SETTINGS_KEY)
    return lenient(AppSettings, row.value if row else None)


def save_folder(settings: AppSettings) -> Path:
    """Where "Save to computer" puts videos: the folder chosen in Settings, or Downloads/Vyral."""
    chosen = settings.storage.save_folder
    return Path(chosen) if chosen else Path(os.environ.get("CLIPPR_DOWNLOADS_DIR") or Path.home() / "Downloads") / "Vyral"


@router.get("/needs-you")
def needs_you(c=Depends(ctx), s: Session = Depends(db)):
    """What's waiting on the user, most important first, each with where it's handled."""
    from ..attention import needs_you as waiting

    items = waiting(s)
    if not c.jobs.online():
        items.insert(0, {"kind": "offline", "count": 1, "title": "No internet connection. Vyral is waiting and carries on by itself when it's back.", "link": "/activity"})
    inbox_error = c.inbox.state(s).get("last_error")
    if inbox_error:
        items.append({"kind": "inbox", "count": 1, "title": f"Discord inbox: {inbox_error}", "link": "/settings?tab=notifications"})
    return items


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
    for name, folder in (("save_folder", new.storage.save_folder), ("media_folder", new.storage.media_folder)):
        if folder:
            try:
                Path(folder).mkdir(parents=True, exist_ok=True)
                (Path(folder) / ".vyral-write-test").write_bytes(b"")
                (Path(folder) / ".vyral-write-test").unlink()
            except OSError as e:
                raise ApiError(422, "folder", f"storage.{name}: Vyral can't write to {folder} ({e.strerror or e})")
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


@router.get("/storage/location")
def storage_location(c=Depends(ctx)):
    from ..config import read_location

    loc = read_location()
    return {"data_dir": str(c.config.data_dir), "disk_free_bytes": shutil.disk_usage(c.config.data_dir).free,
            "pending": loc.get("path") if loc.get("move_from") and not loc.get("error") else None,
            "error": loc.get("error"), "env_override": bool(os.environ.get("CLIPPR_DATA_DIR"))}


def check_move_target(raw: str, current: Path, needed: int) -> Path:
    """Where the data would go; raises ApiError with what's wrong with the folder."""
    raw = (raw or "").strip()
    if not raw or not Path(raw).is_absolute():
        raise ApiError(422, "folder", "Give a full folder path, like D:\\Vyral")
    target = Path(raw)
    if target.exists() and not target.is_dir():
        raise ApiError(422, "folder", f"{target} is a file, not a folder")
    if target.is_dir() and any(target.iterdir()):
        target = target / "Vyral"  # e.g. D:\ chosen: keep Vyral's files together in their own folder
        if target.exists() and (not target.is_dir() or any(target.iterdir())):
            raise ApiError(422, "folder", f"{target} already has files in it. Choose an empty or new folder.")
    cur, tgt = current.resolve(), target.resolve()
    if tgt == cur or tgt.is_relative_to(cur):
        raise ApiError(422, "folder", "That folder is inside Vyral's current data folder. Choose one outside it.")
    try:
        target.mkdir(parents=True, exist_ok=True)
        (target / ".vyral-write-test").write_bytes(b"")
        (target / ".vyral-write-test").unlink()
    except OSError as e:
        raise ApiError(422, "folder", f"Vyral can't write to {target} ({e.strerror or e})")
    free = shutil.disk_usage(target).free
    if free < needed:
        raise ApiError(422, "space", f"Not enough room on that drive: Vyral's data needs about {needed // 2**20} MB, {free // 2**20} MB is free.")
    return target


@router.post("/storage/move")
def move_data(body: dict, c=Depends(ctx), s: Session = Depends(db)):
    """Moves everything at the next start: the folder is checked now, the copy happens before the database opens."""
    from ..config import write_location

    if os.environ.get("CLIPPR_DATA_DIR"):
        raise ApiError(409, "env", "The data folder is fixed by CLIPPR_DATA_DIR on this computer; change that instead.")
    current = c.config.data_dir
    target = check_move_target(str(body.get("path", "")), current, int(_dir_size(current) * 1.1) + 200 * 2**20)
    write_location({"path": str(target), "move_from": str(current)})
    audit(s, "storage.move_requested", "settings", "", {"to": str(target)})
    return {"ok": True, "path": str(target)}


@router.post("/pick-folder")
def pick_folder():
    """Opens this computer's own folder picker (Finder on a Mac, File Explorer on Windows) and returns the folder
    chosen, or null if cancelled. Done here, not in the window: the window gets no direct access to the computer."""
    import subprocess
    import sys
    prompt = "Choose a folder for Vyral"
    if sys.platform == "darwin":
        # Shown by whichever app is in front (Vyral), so it doesn't open behind the window.
        cmd = ["osascript", "-e", f'tell application (path to frontmost application as text) to POSIX path of (choose folder with prompt "{prompt}")']
    elif sys.platform == "win32":
        ps = ("Add-Type -AssemblyName System.Windows.Forms;"
              "$o=New-Object System.Windows.Forms.Form -Property @{TopMost=$true};"
              f"$d=New-Object System.Windows.Forms.FolderBrowserDialog -Property @{{Description='{prompt}';ShowNewFolderButton=$true}};"
              "if($d.ShowDialog($o) -eq 'OK'){[Console]::Out.Write($d.SelectedPath)}")
        cmd = ["powershell", "-NoProfile", "-STA", "-Command", ps]
    else:
        cmd = ["zenity", "--file-selection", "--directory", f"--title={prompt}"]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=600,
                           creationflags=0x08000000 if sys.platform == "win32" else 0)  # no console window
    except FileNotFoundError:
        raise ApiError(501, "unsupported", "This computer has no folder picker Vyral can open. Type the folder's path instead.")
    except subprocess.TimeoutExpired:
        return {"path": None}
    path = r.stdout.strip().rstrip("/\\") if r.returncode == 0 else ""
    return {"path": path or None}  # cancelled: null


# ---------- Obsidian (obsidian.py) ----------
@router.get("/obsidian")
def obsidian_state(s: Session = Depends(db)):
    from .. import obsidian
    return obsidian.view(s)


@router.post("/obsidian/connect")
def obsidian_connect(body: dict, s: Session = Depends(db)):
    from .. import obsidian
    try:
        vault = obsidian.check_vault(str(body.get("path") or ""))
    except ValueError as e:
        raise ApiError(422, "vault", str(e))
    put_settings({"obsidian": {"vault": str(vault)}}, s)
    obsidian._save(s, {})
    obsidian.sync(s)
    return obsidian.view(s)


@router.post("/obsidian/disconnect")
def obsidian_disconnect(s: Session = Depends(db)):
    from .. import obsidian
    put_settings({"obsidian": {"vault": ""}}, s)
    obsidian._save(s, {})
    return obsidian.view(s)  # the notes stay in the vault: they're yours


@router.post("/obsidian/sync")
def obsidian_sync(s: Session = Depends(db)):
    from .. import obsidian
    obsidian.sync(s)
    return obsidian.view(s)

"""Runtime configuration. Everything is local-first; paths default to the OS app-data folder."""
from __future__ import annotations

import json
import os
import platform
import secrets
import shutil
import sqlite3
import tempfile
from dataclasses import dataclass, field
from pathlib import Path


def base_data_dir() -> Path:
    """Where Vyral keeps its data unless the user moved it (the desktop app passes its own folder)."""
    base = os.environ.get("CLIPPR_BASE_DATA_DIR")
    if base:
        return Path(base).expanduser()
    if platform.system() == "Darwin":
        return Path.home() / "Library" / "Application Support" / "Vyral"
    if platform.system() == "Windows":
        return Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming")) / "Vyral"
    return Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")) / "vyral"


def location_file() -> Path:
    """Fixed spot, next to the default data folder, that says where the data lives after "Move Vyral's data"."""
    return base_data_dir().parent / "Vyral-location.json"


def read_location() -> dict:
    try:
        v = json.loads(location_file().read_text("utf-8"))
        return v if isinstance(v, dict) and isinstance(v.get("path"), str) and Path(v["path"]).is_absolute() else {}
    except (OSError, ValueError):
        return {}


def write_location(v: dict) -> None:
    f = location_file()
    f.parent.mkdir(parents=True, exist_ok=True)
    tmp = f.with_suffix(".tmp")
    tmp.write_text(json.dumps(v), "utf-8")
    os.replace(tmp, f)


def default_data_dir() -> Path:
    override = os.environ.get("CLIPPR_DATA_DIR")
    if override:
        return Path(override).expanduser()
    loc = read_location()
    if loc.get("move_from"):  # move pending or failed: the data is still in the old folder
        return Path(loc["move_from"])
    return Path(loc["path"]) if loc else base_data_dir()


def _tree(root: Path) -> dict[str, int]:
    return {str(p.relative_to(root)): p.stat().st_size for p in root.rglob("*") if p.is_file()}


def _repoint_db(db: Path, old: str, new: str) -> None:
    """Clips are stored with full file paths: point the ones inside the old folder at the new one."""
    if not db.exists():
        return
    con = sqlite3.connect(db)
    try:
        with con:
            tables = [r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")]
            for t in tables:
                for col in [r[1] for r in con.execute(f'PRAGMA table_info("{t}")')]:
                    # plain text, and the same path escaped inside JSON (Windows backslashes are doubled there)
                    for a, b in {(old, new), (json.dumps(old)[1:-1], json.dumps(new)[1:-1])}:
                        con.execute(f'UPDATE "{t}" SET "{col}" = replace("{col}", ?, ?) WHERE typeof("{col}") = \'text\' AND instr("{col}", ?) > 0',
                                    (a, b, a))
    finally:
        con.close()


def apply_pending_move() -> None:
    """Runs at startup before the database opens: copies the data to the folder chosen in Settings, checks every
    file arrived, switches over, then deletes the old copy. On failure the old folder stays in use."""
    if os.environ.get("CLIPPR_DATA_DIR"):
        return
    loc = read_location()
    old, new = loc.get("move_from"), loc.get("path")
    if not old or loc.get("error"):
        return
    old, new = Path(old), Path(new)
    try:
        if old.exists():
            shutil.copytree(old, new, dirs_exist_ok=True)
            src, dst = _tree(old), _tree(new)
            missing = [k for k, size in src.items() if dst.get(k) != size]
            if missing:
                raise OSError(f"{len(missing)} files didn't copy correctly, e.g. {missing[0]}")
        else:
            new.mkdir(parents=True, exist_ok=True)
        _repoint_db(new / "clippr.db", str(old), str(new))
    except Exception as e:
        write_location({**loc, "error": f"Couldn't move Vyral's data to {new}: {e}. Still using {old}."})
        return
    write_location({"path": str(new), "moved_from": str(old)})
    # The desktop shell keeps its own log open in the old folder, so whatever can't be deleted yet is left.
    shutil.rmtree(old, ignore_errors=True)


def use_data_dir_for_temp(data_dir: Path) -> None:
    """Keeps downloads in progress, work files and model caches inside the data folder, not on the system drive."""
    tmp = data_dir / "tmp"
    shutil.rmtree(tmp, ignore_errors=True)  # leftovers from a crash
    tmp.mkdir(parents=True, exist_ok=True)
    for k in ("TMP", "TEMP", "TMPDIR"):
        os.environ[k] = str(tmp)
    tempfile.tempdir = str(tmp)
    os.environ.setdefault("HF_HOME", str(data_dir / "models" / "huggingface"))
    os.environ.setdefault("XDG_CACHE_HOME", str(data_dir / "cache"))


@dataclass
class Config:
    data_dir: Path = field(default_factory=default_data_dir)
    host: str = "127.0.0.1"
    port: int = int(os.environ.get("CLIPPR_PORT", "8765"))
    # Per-launch token the UI must send on every /api request. Blocks other local
    # processes' web pages from driving the API (CSRF / DNS-rebinding defence).
    api_token: str = field(default_factory=lambda: os.environ.get("CLIPPR_API_TOKEN") or secrets.token_urlsafe(32))
    # When true (desktop build) the backend opens OAuth pages in the system browser itself.
    desktop_mode: bool = os.environ.get("CLIPPR_DESKTOP") == "1"
    run_worker: bool = os.environ.get("CLIPPR_NO_WORKER") != "1"
    frontend_dist: Path | None = None
    # "auto" uses the OS keychain when available, else an encrypted local file.
    secret_backend: str = os.environ.get("CLIPPR_SECRET_BACKEND", "auto")

    @property
    def db_path(self) -> Path:
        return self.data_dir / "clippr.db"

    @property
    def media_dir(self) -> Path:
        return self.data_dir / "media"

    @property
    def base_url(self) -> str:
        return f"http://{self.host}:{self.port}"

    def ensure_dirs(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        if os.name != "nt":
            os.chmod(self.data_dir, 0o700)
        self.media_dir.mkdir(exist_ok=True)

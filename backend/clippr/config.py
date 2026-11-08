"""Runtime configuration. Everything is local-first; paths default to the OS app-data folder."""
from __future__ import annotations

import os
import platform
import secrets
from dataclasses import dataclass, field
from pathlib import Path


def default_data_dir() -> Path:
    override = os.environ.get("CLIPPR_DATA_DIR")
    if override:
        return Path(override).expanduser()
    if platform.system() == "Darwin":
        return Path.home() / "Library" / "Application Support" / "AI Clipper"
    return Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")) / "ai-clipper"


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
        os.chmod(self.data_dir, 0o700)
        self.media_dir.mkdir(exist_ok=True)

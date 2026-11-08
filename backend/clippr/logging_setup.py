"""Structured JSON logs with secret redaction."""
from __future__ import annotations

import json
import logging
import re
from logging.handlers import RotatingFileHandler
from pathlib import Path

_PATTERNS = [
    re.compile(r"((?:access|refresh|id)_token|client_secret|code_verifier|api[_-]?key|password|authorization)([\"']?\s*[:=]\s*[\"']?)([^\s\"'&,}]+)", re.I),
    re.compile(r"(Bearer\s+)[A-Za-z0-9._\-~+/=]+", re.I),
    re.compile(r"([?&](?:code|state|access_token|client_secret)=)[^&\s]+", re.I),
]


def redact(text: str) -> str:
    for p in _PATTERNS:
        text = p.sub(lambda m: m.group(1) + (m.group(2) if m.lastindex and m.lastindex >= 3 else "") + "[REDACTED]", text)
    return text


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        msg = record.getMessage()
        if record.exc_info:
            msg += "\n" + self.formatException(record.exc_info)
        return json.dumps({"ts": self.formatTime(record), "level": record.levelname, "logger": record.name, "msg": redact(msg)})


def setup_logging(log_dir: Path) -> None:
    log_dir.mkdir(parents=True, exist_ok=True)
    root = logging.getLogger("clippr")
    if root.handlers:
        return
    root.setLevel(logging.INFO)
    fh = RotatingFileHandler(log_dir / "clippr.log", maxBytes=5_000_000, backupCount=5)
    fh.setFormatter(JsonFormatter())
    sh = logging.StreamHandler()
    sh.setFormatter(JsonFormatter())
    root.addHandler(fh)
    root.addHandler(sh)

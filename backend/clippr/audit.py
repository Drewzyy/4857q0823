"""Append-only audit trail of user-visible actions. Never pass secrets in `details`."""
from __future__ import annotations

from typing import Any

from .models import AuditLog

_BLOCKED = ("token", "secret", "password", "code", "cookie")


def audit(session, action: str, entity: str = "", entity_id: Any = "", details: dict[str, Any] | None = None) -> None:
    clean = {k: v for k, v in (details or {}).items() if not any(b in k.lower() for b in _BLOCKED)}
    session.add(AuditLog(action=action, entity=entity, entity_id=str(entity_id), details=clean))

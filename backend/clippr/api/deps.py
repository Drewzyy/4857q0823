from __future__ import annotations

from typing import Any, Iterator

from fastapi import Request
from sqlalchemy.orm import Session


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str, extra: dict[str, Any] | None = None):
        super().__init__(message)
        self.status, self.code, self.message, self.extra = status, code, message, extra or {}


def ctx(request: Request):
    return request.app.state.ctx


def db(request: Request) -> Iterator[Session]:
    with request.app.state.ctx.db.session() as s:
        yield s


def get_or_404(s: Session, model, obj_id: int, label: str):
    obj = s.get(model, obj_id)
    if not obj:
        raise ApiError(404, "not_found", f"{label} not found")
    return obj

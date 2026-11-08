"""App updates. The desktop shell does the actual checking/downloading/installing (signed updates from
the public vyral-releases repo); it reports progress here and picks up the user's requests from here,
so the interface can show "Update ready, restart" without any native access."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from .. import __version__
from .deps import ApiError, ctx

router = APIRouter(prefix="/app-update")


def _state(request: Request) -> dict:
    st = getattr(request.app.state, "update", None)
    if st is None:
        st = request.app.state.update = {
            "state": "idle", "current": __version__, "version": None, "notes": "", "error": None, "progress": None,
            "checked_at": None, "check_requested": False, "install_requested": False,
        }
    return st


@router.get("")
def get_update(request: Request, c=Depends(ctx)):
    st = _state(request)
    return {**st, "available": c.config.desktop_mode}


class Report(BaseModel):
    state: Literal["checking", "none", "downloading", "ready", "installing", "error"]
    version: str | None = Field(None, max_length=40)
    notes: str = Field("", max_length=4000)
    error: str | None = Field(None, max_length=500)
    progress: float | None = Field(None, ge=0, le=1)


@router.post("/report")
def report(body: Report, request: Request):
    """Called by the desktop shell."""
    st = _state(request)
    st.update(state=body.state, version=body.version or st["version"], notes=body.notes or st["notes"], error=body.error, progress=body.progress)
    if body.state == "checking":
        st["check_requested"] = False
    if body.state in ("none", "ready", "error"):
        st["checked_at"] = datetime.now(timezone.utc).isoformat()
    if body.state == "error":
        st["install_requested"] = False
    return st


@router.post("/check")
def check(request: Request, c=Depends(ctx)):
    if not c.config.desktop_mode:
        raise ApiError(409, "unavailable", "Updates are handled by the desktop app")
    st = _state(request)
    if st["state"] in ("checking", "downloading", "installing"):
        return st
    st["check_requested"] = True
    return st


@router.post("/install")
def install(request: Request):
    st = _state(request)
    if st["state"] != "ready":
        raise ApiError(409, "not_ready", "No downloaded update to install yet")
    st["install_requested"] = True
    return st

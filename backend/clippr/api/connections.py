"""Platform setup + account connection endpoints."""
from __future__ import annotations

import logging
import webbrowser
from typing import Literal

from fastapi import APIRouter, Depends, File, UploadFile
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import serialize as ser
from ..models import Connection
from ..platforms.base import PlatformError
from .deps import ApiError, ctx, db

router = APIRouter()
log = logging.getLogger("clippr.api.connections")


def _err(e: PlatformError) -> ApiError:
    status = {"not_found": 404, "setup_required": 409, "validation": 422, "invalid_client": 422, "rate_limited": 429, "network": 502}.get(e.code, 400)
    return ApiError(status, e.code, str(e))


@router.get("/platforms")
def platforms(c=Depends(ctx)):
    return c.connections.platform_status()


class AppCredsIn(BaseModel):
    client_id: str = Field(min_length=1, max_length=300)
    client_secret: str = Field(min_length=1, max_length=300)


@router.put("/platforms/{key}/app")
def set_app(key: str, body: AppCredsIn, c=Depends(ctx)):
    try:
        return c.connections.set_app_credentials(key, body.client_id, body.client_secret)
    except PlatformError as e:
        raise _err(e)


@router.post("/platforms/youtube/client-file")
async def upload_google_client(file: UploadFile = File(...), c=Depends(ctx)):
    raw = await file.read(64_001)
    if len(raw) > 64_000:
        raise ApiError(413, "too_large", "That file is too large to be a Google client file")
    try:
        return c.connections.import_google_client_json(raw.decode("utf-8", errors="replace"))
    except PlatformError as e:
        raise _err(e)


@router.delete("/platforms/{key}/app", status_code=204)
def remove_app(key: str, c=Depends(ctx)):
    try:
        c.connections.remove_app_credentials(key)
    except PlatformError as e:
        raise _err(e)


class StartIn(BaseModel):
    platform: Literal["youtube", "tiktok", "meta"]
    purpose: Literal["destination", "source"] = "destination"
    link_destination_id: int | None = None


@router.post("/connections/start")
def start(body: StartIn, c=Depends(ctx)):
    try:
        attempt, url = c.connections.start(body.platform, body.purpose, body.link_destination_id)
    except PlatformError as e:
        raise _err(e)
    opened = False
    if c.config.desktop_mode:
        try:
            opened = webbrowser.open(url)
        except Exception:
            log.warning("could not open system browser")
    return {"attempt": attempt.public(), "authorize_url": url, "opened_by_app": opened}


@router.get("/connections/attempts/{attempt_id}")
def attempt_status(attempt_id: str, c=Depends(ctx)):
    a = c.connections.attempt(attempt_id)
    if not a:
        raise ApiError(404, "not_found", "Sign-in attempt not found or expired")
    return a.public()


@router.get("/connections")
def list_connections(s: Session = Depends(db)):
    return [ser.connection(x) for x in s.scalars(select(Connection).order_by(Connection.platform, Connection.display_name))]


@router.post("/connections/{cid}/refresh")
def refresh(cid: int, c=Depends(ctx)):
    status = c.connections.refresh(cid)
    if status == "missing":
        raise ApiError(404, "not_found", "Connection not found")
    return {"status": status}


@router.delete("/connections/{cid}", status_code=204)
def disconnect(cid: int, c=Depends(ctx)):
    try:
        c.connections.disconnect(cid)
    except PlatformError as e:
        raise _err(e)

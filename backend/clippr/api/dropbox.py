"""Dropbox auto-upload: connect, status, Sync all and retry (the uploading itself is in dropbox.py)."""
from __future__ import annotations

import webbrowser

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import dropbox as dbx
from ..models import DropboxUpload
from .deps import ApiError, ctx, db
from .system import load_settings

router = APIRouter()


def _view(c, s: Session) -> dict:
    st, cfg = dbx.state(s), load_settings(s).dropbox
    counts = dict(s.execute(select(DropboxUpload.status, func.count()).group_by(DropboxUpload.status)).all())
    return {"connected": bool(st.get("connected")), "needs_reconnect": bool(st.get("needs_reconnect")), "account": st.get("account"),
            "error": st.get("error"), "connect_error": st.get("connect_error"), "connecting": c.dropbox.connecting(), "app_key_set": bool(cfg.app_key), "redirect_uri": dbx.REDIRECT_URI,
            "counts": {k: counts.get(k, 0) for k in ("queued", "uploading", "uploaded", "failed")}}


@router.get("/dropbox")
def get_dropbox(c=Depends(ctx), s: Session = Depends(db)):
    return _view(c, s)


@router.post("/dropbox/connect")
def connect(c=Depends(ctx), s: Session = Depends(db)):
    """Starts signing in: opens Dropbox's page in the browser (the link is returned too, in case it doesn't open)."""
    key = load_settings(s).dropbox.app_key
    if not key:
        raise ApiError(422, "no_app_key", "Paste your Dropbox app's key first (the steps are above the box).")
    dbx._save_state(s, connect_error=None)  # a fresh sign-in with a new code
    try:
        url = c.dropbox.begin_connect(key)
    except dbx.DropboxError as e:
        raise ApiError(409, "port_busy", str(e))
    if c.config.desktop_mode:
        webbrowser.open(url)
    return {"url": url}


@router.post("/dropbox/disconnect")
def disconnect(c=Depends(ctx), s: Session = Depends(db)):
    c.dropbox.disconnect()
    s.expire_all()
    return _view(c, s)


@router.post("/dropbox/sync-all")
def sync_all(c=Depends(ctx), s: Session = Depends(db)):
    if not dbx.state(s).get("connected"):
        raise ApiError(409, "not_connected", "Connect Dropbox first.")
    return {"queued": c.dropbox.sync_all()}


@router.post("/dropbox/uploads/{uid}/retry")
def retry(uid: int, c=Depends(ctx)):
    if not c.dropbox.retry(uid):
        raise ApiError(409, "invalid_state", "Only a failed or waiting upload can be retried.")
    return {"ok": True}

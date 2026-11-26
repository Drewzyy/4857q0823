"""The Vyral Companion browser extension (extension/): posts approved videos for you on the TikTok, Instagram and
YouTube websites, in your own browser, where you're already logged in. No Muse needed.

It asks Vyral, through the Muse bridge (same address and token), for the next video that's due:
- approved by you (watched and approved in Ready to Upload), finished, passed the quality check, not held back;
- for a TikTok, Instagram or YouTube page;
- its time has come: the page's spacing since its last post and inside your posting hours (posting.package);
- the page hasn't reached its daily cap (Destinations > page > Auto-post daily cap).
Then it opens that site's upload page, puts the video in and fills in the caption (and the title on YouTube).

Who presses Post: you, unless the page's Auto-post is on (unlocked after 5 reviewed posts on it), the kill switch
is off and the clip passed the safety check outright; then the extension presses it. The sites' rules don't allow
automated posting, so an account can be flagged for it: Auto-post is yours to turn on, page by page. A captcha, a
login or any check the site shows always stops it and hands over to you; it's never worked around.

Afterwards the extension reports back: with the post's link when the site shows it (YouTube does), else the
video is marked uploaded and its link is found by itself from your page (TikTok, YouTube) or stays unknown
(Instagram can't be read without logging in).
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from . import posting
from .api.system import load_settings
from .audit import audit
from .models import Clip, ClipOutput

PLATFORMS = ("tiktok", "instagram", "youtube")
UPLOAD_PAGES = {"tiktok": "https://www.tiktok.com/tiktokstudio/upload", "instagram": "https://www.instagram.com/",
                "youtube": "https://www.youtube.com/upload"}  # opens YouTube Studio with the upload box
SNOOZE = timedelta(hours=1)  # after a failed try, that video waits this long


def _posted_today(s: Session, dest_id: int) -> int:
    start = datetime.now(timezone.utc).astimezone().replace(hour=0, minute=0, second=0, microsecond=0).astimezone(timezone.utc)
    return s.scalar(select(func.count()).select_from(ClipOutput).where(ClipOutput.destination_id == dest_id, ClipOutput.status == "uploaded",
                                                                       ClipOutput.uploaded_at >= start)) or 0


def next_job(s: Session) -> dict | None:
    """The next video the extension should post now, with everything it needs, or None."""
    cfg = load_settings(s).posting
    now = datetime.now(timezone.utc)
    rows = s.scalars(select(ClipOutput).where(ClipOutput.review == "approved", ClipOutput.status == "ready", ClipOutput.render_state == "ready",
                                              ClipOutput.platform.in_(PLATFORMS), ClipOutput.post_url.is_(None))
                     .order_by(ClipOutput.scheduled_at.is_(None), ClipOutput.scheduled_at, ClipOutput.id)).unique()
    for o in rows:
        tried = (o.post_check or {}).get("companion_failed_at")
        if tried and now - datetime.fromisoformat(tried) < SNOOZE:
            continue
        clip = s.get(Clip, o.clip_id)
        if not clip or posting.held_back(clip, cfg.min_virality) or (o.quality or {}).get("status") == "fail":
            continue
        if o.scheduled_at and o.scheduled_at > now:
            continue
        st = dict(o.destination.settings or {}) if o.destination else {}
        if o.destination_id and _posted_today(s, o.destination_id) >= int(st.get("daily_cap", 3)):
            continue
        try:
            pkg = posting.package(s, o.id)
        except posting.PostingError:
            continue
        if datetime.fromisoformat(pkg["post_after"]) > now:
            continue
        auto = bool(st.get("auto_post")) and not cfg.auto_post_kill_switch and (clip.safety or {}).get("status") == "pass"
        return {**pkg, "upload_page": UPLOAD_PAGES[o.platform], "video": f"/companion/video/{o.id}", "auto": auto,
                "handle": o.destination.handle if o.destination else ""}
    return None


def posted(ctx, oid: int, post_url: str | None) -> dict:
    """The extension posted it. With the link: recorded and checked like Muse's. Without: marked uploaded; the link
    is found from the page later where it can be (TikTok, YouTube)."""
    from .api.analytics import link_post
    with ctx.db.session() as s:
        o = s.get(ClipOutput, oid)
        if not o or o.review != "approved":
            raise ValueError("No approved video with that id")
        if post_url:
            chk = {**posting.check_post(s, ctx.fetcher, o, post_url), "by": "companion"}
            if chk["status"] != "failed":
                link_post(s, ctx.jobs, o, post_url, "companion")
            o.post_check = chk
            return {"recorded": chk["status"] != "failed", "post_check": chk}
        o.status, o.uploaded_at = "uploaded", datetime.now(timezone.utc)
        o.post_check = {"status": "unverified", "by": "companion", "at": o.uploaded_at.isoformat(), "url": "",
                        "reason": "posted by the companion; the link is found from the page when it can be"}
        audit(s, "clip.posted_by_companion", "output", oid, {"platform": o.platform})
        return {"recorded": True, "post_check": o.post_check}


def failed(ctx, oid: int, reason: str) -> dict:
    """The extension couldn't post it (a captcha, a login, the site changed): it waits an hour and the reason shows."""
    with ctx.db.session() as s:
        o = s.get(ClipOutput, oid)
        if not o:
            raise ValueError("No such video")
        o.post_check = {**(o.post_check or {}), "companion_failed_at": datetime.now(timezone.utc).isoformat(),
                        "companion_error": reason[:300]}
        audit(s, "clip.companion_failed", "output", oid, {"reason": reason[:300]})
    return {"ok": True}


def extension_dir():
    """The browser extension's files: packed into the app, or the repository's extension/ folder."""
    from pathlib import Path
    here = Path(__file__).resolve().parent
    for d in (here / "companion_extension", here.parent.parent / "extension"):
        if (d / "manifest.json").exists():
            return d
    return None


def attention(ctx, oid: int, text: str, kind: str = "ready") -> dict:
    """A Discord ping when the extension needs you: a post filled in and waiting for you to press Post ("ready"),
    or a captcha, login or check it stopped at ("stopped"). Once per video and kind."""
    from . import events
    with ctx.db.session() as s:
        o = s.get(ClipOutput, oid)
        if not o:
            raise ValueError("No such video")
        clip = s.get(Clip, o.clip_id)
        page = (o.destination.display_name or o.destination.handle) if o.destination else o.platform
        title = clip.title if clip else ""
    site = {"tiktok": "TikTok", "instagram": "Instagram", "youtube": "YouTube"}.get(o.platform, o.platform)
    head = f"Post ready on {site}: press Post" if kind == "ready" else f"Vyral Companion stopped on {site}: needs you"
    events.emit(ctx, "approvals", head, body=f"{page}: {title}\n{text}"[:500], priority="high" if kind == "ready" else "urgent",
                link=UPLOAD_PAGES.get(o.platform), dedupe_key=f"companion:{kind}:{oid}", data={"output_id": oid})
    return {"ok": True}

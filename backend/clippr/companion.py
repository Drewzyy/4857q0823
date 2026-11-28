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


def next_job(s: Session, why: list[str] | None = None) -> dict | None:
    """The next video the extension should post now, with everything it needs, or None. why, if given, gets the
    reason each approved video is waiting, so the extension can say why nothing is posting."""
    why = [] if why is None else why
    cfg = load_settings(s).posting
    now = datetime.now(timezone.utc)
    rows = s.scalars(select(ClipOutput).where(ClipOutput.review == "approved", ClipOutput.status == "ready", ClipOutput.render_state == "ready",
                                              ClipOutput.platform.in_(PLATFORMS), ClipOutput.post_url.is_(None))
                     .order_by(ClipOutput.scheduled_at.is_(None), ClipOutput.scheduled_at, ClipOutput.id)).unique()
    for o in rows:
        tried = (o.post_check or {}).get("companion_failed_at")
        if tried and now - datetime.fromisoformat(tried) < SNOOZE:
            why.append("one failed a moment ago: tried again in a while")
            continue
        clip = s.get(Clip, o.clip_id)
        if not clip or posting.held_back(clip, cfg.min_virality, you=o.reviewed_by == "you") or (o.quality or {}).get("status") == "fail":
            why.append("held back: " + (posting.held_back(clip, cfg.min_virality, you=o.reviewed_by == "you") or "its video failed the quality check") if clip else "its clip is gone")
            continue
        if o.scheduled_at and o.scheduled_at > now:
            why.append(f"scheduled for {o.scheduled_at:%b %d %H:%M} UTC")
            continue
        st = dict(o.destination.settings or {}) if o.destination else {}
        if o.destination_id and _posted_today(s, o.destination_id) >= int(st.get("daily_cap", 3)):
            why.append(f"{o.destination.handle} already has its {int(st.get('daily_cap', 3))} posts today")
            continue
        try:
            pkg = posting.package(s, o.id)
        except posting.PostingError as e:
            why.append(str(e))
            continue
        if datetime.fromisoformat(pkg["post_after"]) > now:
            why.append(f"next post time {pkg['post_after']} (posting hours and spacing, Settings)")
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
    link = UPLOAD_PAGES.get(o.platform)
    if kind == "ready":
        go = go_link(ctx, oid)
        if go:  # tap it on your phone (Tailscale) to post from anywhere
            link, text = go, f"{text}\nTap the link to post it from your phone."
    events.emit(ctx, "approvals", head, body=f"{page}: {title}\n{text}"[:500], priority="high" if kind == "ready" else "urgent",
                link=link, dedupe_key=f"companion:{kind}:{oid}", data={"output_id": oid})
    return {"ok": True}


# ---- posting from your phone: a one-time link in the Discord ping (over Tailscale) ----
GO_FOR = timedelta(hours=3)
_go: dict[int, dict] = {}  # output id -> {"key", "until", "pressed"}: in memory, gone when Vyral restarts


def go_link(ctx, oid: int) -> str | None:
    """A one-time link that posts this video when you press Post on the page it opens: only made when the bridge is
    on your Tailscale address (a phone can't reach 127.0.0.1), good for one press, for 3 hours."""
    import secrets
    host, port = getattr(ctx.mcp, "host", None), getattr(ctx.mcp, "port", None)
    if not host or host == "127.0.0.1" or not port:
        return None
    key = secrets.token_urlsafe(24)
    _go[oid] = {"key": key, "until": datetime.now(timezone.utc) + GO_FOR, "pressed": False}
    return f"http://{host}:{port}/go/{oid}/{key}"


def go_valid(oid: int, key: str) -> bool:
    import hmac
    g = _go.get(oid)
    return bool(g and not g["pressed"] and datetime.now(timezone.utc) < g["until"] and hmac.compare_digest(g["key"].encode(), key.encode()))


def go_press(oid: int, key: str) -> bool:
    """You pressed Post on your phone: the extension, waiting on the upload page, presses it on the site."""
    if not go_valid(oid, key):
        return False
    _go[oid]["pressed"] = True
    return True


def go_pressed(oid: int) -> bool:
    """For the extension: has Post been pressed from the phone for this video?"""
    g = _go.get(oid)
    return bool(g and g["pressed"])


def go_page(ctx, oid: int) -> dict | None:
    with ctx.db.session() as s:
        o = s.get(ClipOutput, oid)
        if not o:
            return None
        clip = s.get(Clip, o.clip_id)
        return {"site": {"tiktok": "TikTok", "instagram": "Instagram", "youtube": "YouTube"}.get(o.platform, o.platform),
                "page": (o.destination.display_name or o.destination.handle) if o.destination else o.platform,
                "title": clip.title if clip else "", "caption": o.description, "thumb": bool(o.file_path) and o.file_path}


def accounts(s: Session) -> list[dict]:
    """Your enabled pages on the sites the extension posts to, for its Accounts list (who should be signed in where)."""
    from .models import DestinationAccount
    rows = s.scalars(select(DestinationAccount).where(DestinationAccount.enabled.is_(True), DestinationAccount.platform.in_(PLATFORMS))
                     .order_by(DestinationAccount.platform, DestinationAccount.id)).unique()
    return [{"id": d.id, "platform": d.platform, "handle": d.handle or "", "display_name": d.display_name,
             "upload_page": UPLOAD_PAGES[d.platform]} for d in rows]


def open_sites(s: Session) -> list[str]:
    """The upload page of each site your pages post to, opened in Chrome (where the extension lives) when Vyral
    starts, so they're signed in and ready. Settings > Muse & posting turns it off."""
    import shutil
    import subprocess
    import sys
    import webbrowser
    from .models import DestinationAccount
    if not load_settings(s).posting.open_sites_on_start:
        return []
    sites = sorted({d.platform for d in s.scalars(select(DestinationAccount).where(DestinationAccount.enabled.is_(True))).unique()
                    if d.platform in UPLOAD_PAGES})
    urls = [UPLOAD_PAGES[p] for p in sites]
    for url in urls:
        try:
            if sys.platform == "darwin":
                subprocess.run(["open", "-a", "Google Chrome", url], check=True, timeout=20)
            elif sys.platform == "win32":
                subprocess.run(["cmd", "/c", "start", "", "chrome", url], check=True, timeout=20)
            elif shutil.which("google-chrome"):
                subprocess.Popen(["google-chrome", url])
            else:
                webbrowser.open(url)
        except Exception:
            webbrowser.open(url)  # no Chrome found: the default browser
    return urls


# ---- is the extension connected, and signed in where it should be: its heartbeat (POST /companion/status) ----
_beat: dict = {}  # the latest heartbeat, in memory: gone when Vyral restarts until the extension's next tick
SITE_NAMES = {"tiktok": "TikTok", "instagram": "Instagram", "youtube": "YouTube"}


def _norm(v) -> str:
    return str(v or "").strip().removeprefix("@").lower()


def light(acc: dict, seen: dict | None) -> tuple[str, str]:
    """(green | amber | grey, text) for one page: the same rules as the extension's accounts.js."""
    if not seen or seen.get("signedIn") is None:
        return "amber", "Can't tell: open the site"
    if seen.get("signedIn") is False:
        return "grey", "Not signed in"
    shown = seen.get("handle") or seen.get("name")
    if not shown:
        return "amber", "Signed in: open Studio to check the channel"
    if _norm(shown) in (_norm(acc.get("handle")), _norm(acc.get("display_name"))):
        return "green", "Signed in, ready to post"
    return "amber", f"Signed in as {seen.get('handle') or shown}: switch account"


def heartbeat(body: dict) -> dict:
    """The extension's tick: its version, whether posting is on, and who it saw signed in on each site. Kept as
    plain short strings only (never anything else from the pages)."""
    seen = {}
    for p, v in (body.get("seen") or {}).items() if isinstance(body.get("seen"), dict) else ():
        if p in PLATFORMS and isinstance(v, dict):
            si = v.get("signedIn")
            seen[p] = {"signedIn": si if isinstance(si, bool) else None, "handle": str(v.get("handle") or "")[:60] or None,
                       "name": str(v.get("name") or "")[:100] or None, "at": str(v.get("at") or "")[:40] or None}
    try:
        every = min(60.0, max(1.0, float(body.get("every") or 5)))
    except (TypeError, ValueError):
        every = 5.0
    _beat.clear()
    _beat.update(version=str(body.get("version") or "")[:20], enabled=bool(body.get("enabled")), every=every, seen=seen,
                 at=datetime.now(timezone.utc))
    return {"ok": True, "bundled_version": bundled_version()}


def status(s: Session, data_dir=None) -> dict:
    """For the app: is the extension connected (a heartbeat within twice its interval), and each page's light."""
    now = datetime.now(timezone.utc)
    at = _beat.get("at")
    connected = bool(at and now - at <= timedelta(minutes=2 * _beat.get("every", 5)))
    seen = _beat.get("seen", {}) if connected else {}
    rows = []
    for a in accounts(s):
        lt, text = light(a, seen.get(a["platform"]))
        rows.append({**a, "site": SITE_NAMES[a["platform"]], "light": lt, "text": text, "seen": seen.get(a["platform"])})
    return {"connected": connected, "last_seen": at.isoformat() if at else None, "version": _beat.get("version") or None,
            "enabled": bool(_beat.get("enabled")) if connected else False, "bundled_version": bundled_version(),
            "folder": str(install_folder(data_dir)) if data_dir else None, "accounts": rows}


# ---- updating it: the bundled extension, copied to a folder that stays put, for Chrome's Load unpacked ----
def _version(d) -> str | None:
    import json
    if d is None:
        return None
    try:
        return str(json.loads((d / "manifest.json").read_text(encoding="utf-8")).get("version") or "") or None
    except (OSError, ValueError, AttributeError):
        return None


def bundled_version() -> str | None:
    return _version(extension_dir())


def install_folder(data_dir):
    from pathlib import Path
    return Path(data_dir) / "chrome-extension"


def install(data_dir) -> dict:
    """Copy the bundled extension to <data folder>/chrome-extension when its version differs, atomically (a full copy
    beside it, then swapped in), so Chrome loading the folder never sees half a version. The extension reloads itself
    when it sees the newer version (background.js)."""
    import os
    import shutil
    src, dest = extension_dir(), install_folder(data_dir)
    if not src:
        return {"copied": False, "folder": str(dest), "reason": "no extension in this copy of Vyral"}
    want = _version(src)
    if dest.exists() and _version(dest) == want:
        return {"copied": False, "folder": str(dest), "version": want}
    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp, old = dest.with_name(f".{dest.name}.new-{os.getpid()}"), dest.with_name(f".{dest.name}.old-{os.getpid()}")
    shutil.rmtree(tmp, ignore_errors=True)
    shutil.rmtree(old, ignore_errors=True)
    shutil.copytree(src, tmp)
    if dest.exists():
        os.replace(dest, old)
    os.replace(tmp, dest)
    shutil.rmtree(old, ignore_errors=True)
    return {"copied": True, "folder": str(dest), "version": want}

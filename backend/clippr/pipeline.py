"""The automatic loop: watch source accounts -> new post -> find the original stream moment ->
cut it in full quality -> render per destination format -> captions -> Ready to Upload -> Discord.

Every step is a persistent job, so a crash or restart resumes where it left off.
"""
from __future__ import annotations

import logging
import random
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import httpx
from sqlalchemy import select

from . import describe, notify
from .api.system import load_settings
from .audit import audit
from .fetch import MONITORABLE, FetchError, RemotePost
from .jobs import PermanentJobError
from .media import match
from .media.ffmpeg import FFmpegError, probe
from .media.render import OutputFormat, render
from .models import Clip, ClipOutput, Creator, DestinationAccount, ReferenceVideo, SourceAccount, VodAsset
from .routing import resolve_destinations

log = logging.getLogger("clippr.pipeline")
POSTS_PER_CHECK = 12


def now() -> datetime:
    return datetime.now(timezone.utc)


class Pipeline:
    def __init__(self, ctx: Any):
        self.ctx = ctx

    # ---------- paths ----------
    @property
    def media(self) -> Path:
        return self.ctx.config.media_dir

    def _dir(self, name: str) -> Path:
        d = self.media / name
        d.mkdir(parents=True, exist_ok=True)
        return d

    # ---------- notifications ----------
    def notify(self, kind: str, payload: dict) -> None:
        if not self.ctx.secrets.get(notify.SECRET_KEY):
            return
        with self.ctx.db.session() as s:
            if not notify.prefs(s).get(kind, True):
                return
        self.ctx.jobs.enqueue("notify.discord", payload, max_attempts=4)

    def send_discord(self, payload: dict) -> dict:
        hook = (self.ctx.secrets.get(notify.SECRET_KEY) or {}).get("url")
        if not hook:
            return {"skipped": "no webhook"}
        try:
            with httpx.Client(timeout=15) as http:
                notify.send(http, hook, payload)
        except notify.NotifyError as e:
            if "rejected" in str(e):
                raise PermanentJobError(str(e))
            raise
        return {"sent": True}

    # ---------- monitoring ----------
    def tick(self) -> dict:
        """Runs every minute: queue a check for each account that's due."""
        with self.ctx.db.session() as s:
            st = load_settings(s).monitoring
            if not st.enabled:
                return {"monitoring": "off"}
            due = s.scalars(select(SourceAccount).where(
                SourceAccount.monitoring == "active", SourceAccount.platform.in_(MONITORABLE),
                (SourceAccount.next_check_at.is_(None)) | (SourceAccount.next_check_at <= now()))).unique().all()
            for i, src in enumerate(due):
                # Spread checks out so we never hit a platform with a burst of requests.
                src.next_check_at = now() + timedelta(minutes=st.interval_minutes, seconds=random.randint(0, 90))
                self.ctx.jobs.enqueue("source.check", {"source_id": src.id}, idempotency_key=f"check:{src.id}:{int(now().timestamp() // 60)}",
                                      max_attempts=1, delay=i * random.uniform(4, 10))
        return {"queued": len(due)}

    def check_source(self, source_id: int) -> dict:
        with self.ctx.db.session() as s:
            src = s.get(SourceAccount, source_id)
            if not src or src.monitoring != "active":
                return {"skipped": True}
            platform, username, profile = src.platform, src.username, src.profile_url
            interval = load_settings(s).monitoring.interval_minutes
        try:
            posts = self.ctx.fetcher.recent_posts(platform, username, profile, POSTS_PER_CHECK)
        except FetchError as e:
            with self.ctx.db.session() as s:
                src = s.get(SourceAccount, source_id)
                src.error_count += 1
                src.last_error = f"Couldn't check this account: {e}"
                # Back off: 2x, 4x, 8x... the normal interval, up to 6 hours.
                src.next_check_at = now() + timedelta(minutes=min(interval * 2 ** src.error_count, 360))
            return {"error": str(e)}
        new_refs: list[int] = []
        with self.ctx.db.session() as s:
            src = s.get(SourceAccount, source_id)
            first = not src.baseline_done
            known = set(s.scalars(select(ReferenceVideo.external_id).where(ReferenceVideo.platform == platform,
                                                                            ReferenceVideo.external_id.in_([p.id for p in posts]))))
            for p in reversed(posts):  # oldest first
                if p.id in known:
                    continue
                ref = self._new_ref(s, src, p, "baseline" if first else "new")
                if not first:
                    new_refs.append(ref.id)
            src.baseline_done, src.last_synced_at, src.last_error, src.error_count = True, now(), None, 0
        for rid in new_refs:
            with self.ctx.db.session() as s:
                r = s.get(ReferenceVideo, rid)
                self.notify("on_new_post", notify.new_post_message(username, platform, r.title, r.url, r.thumbnail_url))
            self.ctx.jobs.enqueue("clip.build", {"reference_id": rid}, idempotency_key=f"build:{rid}", max_attempts=3)
        return {"posts_seen": len(posts), "new": len(new_refs), "baseline": first}

    def _new_ref(self, s, src: SourceAccount | None, p: RemotePost, status: str, platform: str | None = None) -> ReferenceVideo:
        ref = ReferenceVideo(source_id=src.id if src else None, creator_id=src.creator_id if src else None,
                             platform=platform or (src.platform if src else "tiktok"), external_id=p.id, url=p.url, title=p.title,
                             thumbnail_url=p.thumbnail, posted_at=p.posted_at, duration=p.duration, views=p.views, likes=p.likes,
                             comments=p.comments, shares=p.shares, status=status,
                             status_detail="Already posted before Vyral started watching" if status == "baseline" else "Queued")
        s.add(ref)
        s.flush()
        return ref

    def add_manual(self, url: str, source_id: int | None, creator_id: int | None) -> int:
        """User pasted a post link: build a clip from it right away."""
        post = self.ctx.fetcher.post_details(url)
        platform = "youtube" if "youtu" in url else "instagram" if "instagram.com" in url else "tiktok"
        with self.ctx.db.session() as s:
            existing = s.scalar(select(ReferenceVideo).where(ReferenceVideo.platform == platform, ReferenceVideo.external_id == post.id))
            if existing:
                ref = existing
                if creator_id:
                    ref.creator_id = creator_id
                ref.status, ref.status_detail = "new", "Queued"
            else:
                src = s.get(SourceAccount, source_id) if source_id else None
                ref = self._new_ref(s, src, post, "new", platform)
                if creator_id:
                    ref.creator_id = creator_id
            rid = ref.id
        self.ctx.jobs.enqueue("clip.build", {"reference_id": rid}, max_attempts=3)
        return rid

    # ---------- clip building ----------
    def _set(self, rid: int, status: str, detail: str, **fields) -> None:
        with self.ctx.db.session() as s:
            r = s.get(ReferenceVideo, rid)
            r.status, r.status_detail = status, detail
            for k, v in fields.items():
                setattr(r, k, v)

    def _stop(self, rid: int, status: str, detail: str, account: str | None, url: str) -> dict:
        self._set(rid, status, detail)
        self.notify("on_problem", notify.problem_message(account, detail, url))
        return {"status": status, "detail": detail}

    def _vod_features(self, url: str, title: str = "") -> Any:
        with self.ctx.db.session() as s:
            asset = s.scalar(select(VodAsset).where(VodAsset.url == url))
            if asset and asset.features_path and Path(asset.features_path).exists():
                asset.last_used_at = now()
                return match.load_features(Path(asset.features_path))
        tmp = self._dir("tmp") / f"vod-{random.randrange(1 << 30)}"
        try:
            audio = self.ctx.fetcher.download_audio(url, tmp)
            feats = match.extract_features(audio)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)  # keep only the compact features, never the stream audio
        path = self._dir("vods") / f"{abs(hash(url)) % 10**12}-{int(now().timestamp())}.npy"
        match.save_features(feats, path)
        with self.ctx.db.session() as s:
            asset = s.scalar(select(VodAsset).where(VodAsset.url == url)) or VodAsset(url=url)
            asset.title, asset.duration, asset.features_path, asset.last_used_at = title, len(feats) / match.FPS, str(path), now()
            s.add(asset)
        return feats

    def build_clip(self, rid: int, vod_override: str | None = None) -> dict:
        with self.ctx.db.session() as s:
            ref = s.get(ReferenceVideo, rid)
            if not ref:
                return {"skipped": True}
            src = ref.source
            account = src.username if src else None
            creator = s.get(Creator, ref.creator_id) if ref.creator_id else (src.creator if src else None)
            cfg = load_settings(s)
            if not creator:
                return self._stop(rid, "needs_setup", "Assign this source account to a creator so Vyral knows whose streams to search.", account, ref.url)
            if not creator.clip_permission:
                return self._stop(rid, "needs_setup", f"Confirm you have permission to clip {creator.name} (Creators > Edit).", account, ref.url)
            channels = [vod_override] if vod_override else list(creator.vod_channels or [])
            if not channels:
                return self._stop(rid, "needs_setup", f"Add {creator.name}'s Twitch or YouTube channel so Vyral can find the full stream.", account, ref.url)
            if src:
                dests = [r.destination for r in resolve_destinations(s, src.id)]
            else:
                dests = list(s.scalars(select(DestinationAccount).where(DestinationAccount.creator_id == creator.id, DestinationAccount.enabled.is_(True))).unique())
            if not dests:
                where = f"@{account}" if account else creator.name
                return self._stop(rid, "needs_setup", f"Route {where} to at least one destination in the Account Funnel.", account, ref.url)
            dest_info = [(d.id, d.platform, d.display_name, d.handle, dict(d.settings or {})) for d in dests]
            creator_name, ref_url, ref_title = creator.name, ref.url, ref.title
        self._set(rid, "processing", "Listening to the post")
        work = self._dir("tmp") / f"build-{rid}-{random.randrange(1 << 30)}"
        try:
            ref_audio = self.ctx.fetcher.download_audio(ref_url, work / "ref")
            ref_feats = match.extract_features(ref_audio)

            found = None
            searched = 0
            for ch in channels:
                vods = self.ctx.fetcher.recent_vods(ch, cfg.monitoring.streams_to_search)
                for v in vods:
                    searched += 1
                    self._set(rid, "processing", f"Searching {creator_name}'s stream {searched}: {v.title or v.url}"[:300])
                    m = match.find_in_stream(ref_feats, self._vod_features(v.url, v.title))
                    if m:
                        found = (v, m)
                        break
                if found:
                    break
            if not found:
                return self._stop(rid, "no_match", f"Couldn't find this moment in {creator_name}'s last {searched} stream(s). "
                                  "If it's from an older stream, paste that stream's link with Retry.", account, ref_url)
            vod, m = found
            if m.end - m.start > cfg.monitoring.max_clip_seconds:
                m.end = m.start + cfg.monitoring.max_clip_seconds
            self._set(rid, "processing", f"Found it at {_hms(m.start)} in \"{vod.title or 'stream'}\". Downloading full quality",
                      vod_url=vod.url, vod_start=m.start, vod_end=m.end, match_confidence=m.confidence)

            lead = 8.0
            section = self.ctx.fetcher.download_section(vod.url, max(0.0, m.start - lead), m.end + 3, work / "section")
            # The download may start at a keyframe before the requested time; re-align on audio for a frame-exact cut.
            local = match.find_in_stream(ref_feats, match.extract_features(section), pad=0.4)
            start, dur = (local.start, local.end - local.start) if local else (min(lead, m.start), m.end - m.start)

            self._set(rid, "processing", "Rendering")
            clip_dir = self._dir("clips") / f"ref{rid}-{int(now().timestamp())}"
            renders: dict[str, Path] = {}
            for _, _, _, _, st in dest_info:
                fmt = OutputFormat.from_settings(st.get("format") or {})
                if fmt.key not in renders:
                    renders[fmt.key] = render(section, clip_dir / f"{fmt.key}.mp4", fmt, start=start, duration=dur)

            with self.ctx.db.session() as s:
                clip = Clip(reference_id=rid, creator_id=ref.creator_id or (src.creator_id if src else None), title=describe.clean_title(ref_title, creator_name),
                            vod_url=vod.url, vod_start=m.start, vod_end=m.end, status="ready",
                            expires_at=now() + timedelta(days=cfg.storage.retention_days))
                s.add(clip)
                s.flush()
                for did, platform, _, _, st in dest_info:
                    fmt = OutputFormat.from_settings(st.get("format") or {})
                    path = renders[fmt.key]
                    info = probe(path)
                    title, desc = describe.build(platform, ref_title, creator_name, st)
                    s.add(ClipOutput(clip_id=clip.id, destination_id=did, platform=platform, title=title, description=desc,
                                     file_path=str(path), width=info.width, height=info.height, fps=info.fps, size_bytes=path.stat().st_size))
                audit(s, "clip.ready", "clip", clip.id, {"reference": rid, "destinations": len(dest_info)})
                clip_title = clip.title
            self._set(rid, "ready", f"Ready to upload to {len(dest_info)} destination(s)")
            self.notify("on_clip_ready", notify.ready_message(clip_title, creator_name, [(p, n, h) for _, p, n, h, _ in dest_info]))
            return {"status": "ready", "outputs": len(dest_info)}
        except FetchError as e:
            self._set(rid, "failed", f"Download problem: {e}")
            raise  # retried with backoff by the job queue
        except FFmpegError as e:
            return self._stop(rid, "failed", str(e), account, ref_url)
        finally:
            shutil.rmtree(work, ignore_errors=True)

    # ---------- storage ----------
    def cleanup(self) -> dict:
        """Delete clips and cached media older than the retention period."""
        with self.ctx.db.session() as s:
            days = load_settings(s).storage.retention_days
            cutoff = now() - timedelta(days=days)
            expired = 0
            for clip in s.scalars(select(Clip).where(Clip.status == "ready", Clip.expires_at <= now())).unique():
                for o in s.scalars(select(ClipOutput).where(ClipOutput.clip_id == clip.id)).unique():
                    if o.file_path:
                        Path(o.file_path).unlink(missing_ok=True)
                        try:
                            Path(o.file_path).parent.rmdir()
                        except OSError:
                            pass
                    o.file_path, o.status = None, "expired"
                clip.status = "expired"
                expired += 1
            vods = 0
            for v in s.scalars(select(VodAsset).where(VodAsset.last_used_at <= cutoff)):
                if v.features_path:
                    Path(v.features_path).unlink(missing_ok=True)
                s.delete(v)
                vods += 1
        tmp = self.media / "tmp"
        if tmp.exists():
            for p in tmp.iterdir():
                if datetime.fromtimestamp(p.stat().st_mtime, timezone.utc) < now() - timedelta(hours=12):
                    shutil.rmtree(p, ignore_errors=True) if p.is_dir() else p.unlink(missing_ok=True)
        return {"clips_expired": expired, "streams_forgotten": vods}


def _hms(sec: float) -> str:
    sec = int(sec)
    return f"{sec // 3600}:{sec % 3600 // 60:02d}:{sec % 60:02d}"


def register(ctx: Any) -> Pipeline:
    p = Pipeline(ctx)
    ctx.pipeline = p
    q = ctx.jobs
    q.register("monitor.tick", lambda jc, pl: p.tick())
    q.register("source.check", lambda jc, pl: p.check_source(pl["source_id"]))
    q.register("clip.build", lambda jc, pl: p.build_clip(pl["reference_id"], pl.get("vod_url")))
    q.register("notify.discord", lambda jc, pl: p.send_discord(pl))
    q.register("storage.cleanup", lambda jc, pl: p.cleanup())
    q.every("monitor.tick", 60)
    q.every("storage.cleanup", 6 * 3600)
    q.heavy = {"clip.build"}
    return p

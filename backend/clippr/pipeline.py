"""The automatic loop: watch source accounts -> new post -> find the original stream moment ->
cut it in full quality -> render per destination format -> captions -> Ready to Upload -> Discord.

Every step is a persistent job, so a crash or restart resumes where it left off.
"""
from __future__ import annotations

import json
import logging
import random
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

from sqlalchemy import delete, func, or_, select

from . import describe, events, identify, notify
from .api.system import load_settings
from .audit import audit
from .fetch import MONITORABLE, FetchError, RemotePost
from .media import match, overlay
from .media.ffmpeg import FFmpegError, probe, run
from .media.overlay import Word
from .media.render import OutputFormat, render
from .media.transcribe import TranscribeError
from .models import Clip, ClipOutput, Creator, DestinationAccount, Job, MetricSnapshot, ReferenceVideo, SourceAccount, VodAsset
from .routing import resolve_destinations, source_creator_ids
from .schemas import ClipEdit, OverlaySettings, lenient

log = logging.getLogger("clippr.pipeline")
POSTS_PER_CHECK = 12
LIVE_RETRY_SECONDS = 1800
LIVE_WAITS = 24  # a still-live stream is looked at again every 30 minutes, for up to 12 hours


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
                                      max_attempts=1, delay=i * random.uniform(4, 10), session=s)
        return {"queued": len(due)}

    def check_source(self, source_id: int) -> dict:
        with self.ctx.db.session() as s:
            src = s.get(SourceAccount, source_id)
            if not src or src.monitoring != "active":
                return {"skipped": True}
            platform, username, profile = src.platform, src.username, src.profile_url
            mon = load_settings(s).monitoring
            interval = mon.interval_minutes
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
            fresh = [p for p in posts if p.id not in known]
            if platform == "twitch":
                # Viewers clip the best moments; take the most-watched few. Clips below the bar aren't stored,
                # so they're looked at again on the next check once more people have seen them.
                fresh = [p for p in fresh if (p.views or 0) >= mon.twitch_min_views][:mon.twitch_clips_per_check]
            else:
                fresh.reverse()  # oldest first
            for p in fresh:  # Twitch: most-watched first, so the best clip of a moment is the one that's made
                # The first successful check only skips what was posted before the account was added,
                # so posts made while earlier checks were failing still get clipped.
                is_new = not first or bool(p.posted_at and p.posted_at > src.created_at)
                ref = self._new_ref(s, src, p, "new" if is_new else "baseline")
                if is_new:
                    new_refs.append(ref.id)
            src.baseline_done, src.last_synced_at, src.last_error, src.error_count = True, now(), None, 0
        for rid in new_refs:
            with self.ctx.db.session() as s:
                r = s.get(ReferenceVideo, rid)
                title, url, thumb = r.title, r.url, r.thumbnail_url
            events.emit(self.ctx, "production", f"@{username} posted a new video", body=title[:500], priority="low", link=url,
                        dedupe_key=f"post:{rid}", discord=notify.new_post_message(username, platform, title, url, thumb))
            self.ctx.jobs.enqueue("clip.build", {"reference_id": rid}, idempotency_key=f"build:{rid}", max_attempts=3)
        return {"posts_seen": len(posts), "new": len(new_refs), "baseline": first}

    def _new_ref(self, s, src: SourceAccount | None, p: RemotePost, status: str, platform: str | None = None) -> ReferenceVideo:
        # Single-streamer accounts are attributed now; multi-streamer accounts once the moment is found.
        only = source_creator_ids(src) if src else []
        ref = ReferenceVideo(source_id=src.id if src else None, creator_id=only[0] if len(only) == 1 else None,
                             platform=platform or (src.platform if src else "tiktok"), external_id=p.id, url=p.url, title=p.title,
                             thumbnail_url=p.thumbnail, posted_at=p.posted_at, duration=p.duration, views=p.views, likes=p.likes,
                             comments=p.comments, shares=p.shares, status=status,
                             status_detail="Already posted before Vyral started watching" if status == "baseline" else "Queued")
        s.add(ref)
        s.flush()
        return ref

    def intake_link(self, url: str, creator_id: int | None = None) -> dict:
        """A link the user copied or pasted in a batch: clip it unless Vyral already has (or is making) it."""
        post = self.ctx.fetcher.post_details(url)
        with self.ctx.db.session() as s:
            have = s.scalar(select(ReferenceVideo.status).where(ReferenceVideo.platform == _link_platform(url),
                                                               ReferenceVideo.external_id == post.id))
        if have and have not in ("failed", "no_match", "needs_setup"):
            return {"skipped": f"already {have}"}
        return {"reference_id": self.add_manual(url, None, creator_id, post)}

    def add_manual(self, url: str, source_id: int | None, creator_id: int | None, post: RemotePost | None = None) -> int:
        """User pasted a post link: build a clip from it right away."""
        post = post or self.ctx.fetcher.post_details(url)
        platform = _link_platform(url)
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
        # Once per post and outcome: a retry that hits the same problem doesn't ping again.
        events.emit(self.ctx, "production", f"Couldn't make a clip from {'@' + account + chr(39) + 's post' if account else 'a post'}",
                    body=detail, priority="high", link=url, dedupe_key=f"problem:{rid}:{status}:{detail[:60]}",
                    discord=notify.problem_message(account, detail, url))
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

    def _search_order(self, candidates: list, text: str, posted_at: datetime | None, per_channel: int) -> list:
        """Every candidate stream, most likely first: streams of the streamer the post names, then streams that
        started before the post was made, newest first (one that started after it can't contain the moment).
        One quick lookup per stream gives its start time and whether it's still live."""
        entries = []
        for rank, (cid, cname, channels) in enumerate(candidates):
            for ch in channels:
                score = identify.mention_score(cname, text) + identify.mention_score(identify.channel_handle(ch), text)
                for v in self.ctx.fetcher.recent_vods(ch, per_channel):
                    try:
                        v = self.ctx.fetcher.vod_details(v.url)
                    except FetchError:
                        pass  # search it anyway, just without its start time
                    entries.append((score, rank, v, cid, cname))

        def likelihood(e):
            score, rank, v, *_ = e
            after_post = bool(posted_at and v.published_at and v.published_at > posted_at)
            return (-score, after_post, -(v.published_at.timestamp() if v.published_at else 0), rank)

        return [(v, cid, cname) for _, _, v, cid, cname in sorted(entries, key=likelihood)]

    def build_clip(self, rid: int, vod_override: str | None = None, waits: int = 0,
                   stop_requested: Callable[[], bool] = lambda: False) -> dict:
        with self.ctx.db.session() as s:
            ref = s.get(ReferenceVideo, rid)
            if not ref:
                return {"skipped": True}
            src = ref.source
            account = src.username if src else None
            cfg = load_settings(s)
            # A clipping account can cover several streamers: search each one's streams until the moment is found.
            # With no streamer known (a pasted link, or an account with none assigned), every streamer is a candidate.
            ids = [ref.creator_id] if ref.creator_id else (source_creator_ids(src) if src else [])
            creators = [c for c in (s.get(Creator, i) for i in ids) if c] if ids else list(s.scalars(select(Creator).order_by(Creator.id)))
            if not creators:
                return self._stop(rid, "needs_setup", "Add the streamer under Source Accounts > Creators, with their Twitch, YouTube "
                                  "or Kick channel, so Vyral knows whose streams to search.", account, ref.url)
            usable = [c for c in creators if c.clip_permission and (vod_override or c.vod_channels)]
            if not usable:
                c = creators[0]
                why = (f"Confirm you have permission to clip {c.name} (Creators > Edit)." if not c.clip_permission
                       else f"Add {c.name}'s Twitch, YouTube or Kick channel so Vyral can find the full stream.")
                return self._stop(rid, "needs_setup", why, account, ref.url)
            # Streamers named in the caption, hashtags or @mentions are searched first.
            candidates = identify.rank_candidates(
                [(c.id, c.name, [vod_override] if vod_override else list(c.vod_channels or [])) for c in usable],
                f"{ref.title or ''} {account or ''}")  # a Twitch clip's own channel, or a page named after a streamer, counts too
            if src:
                dests = [r.destination for r in resolve_destinations(s, src.id)]
            else:  # a pasted link goes to the matched streamer's pages and to pages not tied to any streamer
                dests = list(s.scalars(select(DestinationAccount).where(
                    DestinationAccount.enabled.is_(True),
                    or_(DestinationAccount.creator_id.in_([c.id for c in usable]), DestinationAccount.creator_id.is_(None)))).unique())
            if not dests:
                where = f"@{account}" if account else usable[0].name
                return self._stop(rid, "needs_setup", f"Route {where} to at least one destination in the Account Funnel.", account, ref.url)
            all_dests = [(d.id, d.platform, d.display_name, d.handle, dict(d.settings or {}), d.creator_id) for d in dests]
            from_twitch = ref.platform == "twitch"
            ref_url, ref_title, posted_at = ref.url, ref.title, ref.posted_at
        self._set(rid, "processing", "Listening to the post")
        work = self._dir("tmp") / f"build-{rid}-{random.randrange(1 << 30)}"
        try:
            ref_audio = self.ctx.fetcher.download_audio(ref_url, work / "ref")
            ref_feats = match.extract_features(ref_audio)

            found, searched, live = None, 0, []
            self._set(rid, "processing", "Finding the most likely streams")
            for v, cid, cname in self._search_order(candidates, f"{ref_title or ''} {account or ''}", posted_at, cfg.monitoring.streams_to_search):
                if stop_requested():  # the user pressed Stop; the job is already marked cancelled
                    return {"status": "stopped"}
                if v.is_live:
                    live.append(cname)  # downloading a stream that's still going would never finish
                    continue
                searched += 1
                self._set(rid, "processing", f"Searching {cname}'s stream {searched}: {v.title or v.url}"[:300])
                m = match.find_in_stream(ref_feats, self._vod_features(v.url, v.title))
                if m:
                    found = (v, m, cid, cname)
                    break
            names = " / ".join(n for _, n, _ in candidates)
            if not found and live and waits < LIVE_WAITS:
                who = " / ".join(dict.fromkeys(live))
                self._set(rid, "new", f"Not in {searched} finished stream(s), and {who} is still live. "
                          "Vyral looks again every 30 minutes until the stream ends.")
                self.ctx.jobs.enqueue("clip.build", {"reference_id": rid, "vod_url": vod_override, "waits": waits + 1},
                                      delay=LIVE_RETRY_SECONDS, max_attempts=3)
                return {"status": "waiting_for_live_stream"}
            if not found:
                return self._stop(rid, "no_match", f"Couldn't find this moment in {names}'s last {searched} stream(s). "
                                  "If it's from an older stream, paste that stream's link with Retry.", account, ref_url)
            vod, m, matched_id, creator_name = found
            # Many viewers clip the same Twitch moment: make it once.
            with self.ctx.db.session() as s:
                for c in s.scalars(select(Clip).where(Clip.vod_url == vod.url, Clip.vod_start.is_not(None))) if from_twitch else []:
                    overlap = min(c.vod_end, m.end) - max(c.vod_start, m.start)
                    if overlap > 0.5 * min(c.vod_end - c.vod_start, m.end - m.start):
                        self._set(rid, "duplicate", f"Same moment as \"{c.title}\", which Vyral already made")
                        return {"status": "duplicate", "clip_id": c.id}
            # A page tied to another streamer this account also covers doesn't get the clip (B's moment
            # isn't A's content). Every other routed page does: pages tied to this streamer or to nobody,
            # and pages the user routed this account to on purpose, like a group page for its members.
            covered = {cid for cid, _, _ in candidates} if src else set()
            dest_info = [d[:5] for d in all_dests if d[5] in (None, matched_id) or (src and d[5] not in covered)]
            if not dest_info:
                others = ", ".join(d[2] for d in all_dests)
                where = (f"@{account}'s pages ({others}) are each set to another streamer it covers. Under Destinations, set one to "
                         f"{creator_name} or to Any streamer" if account else f"there's no {creator_name} page under Destinations")
                return self._stop(rid, "needs_setup", f"This is a {creator_name} clip, but {where}.", account, ref_url)
            with self.ctx.db.session() as s:
                s.get(ReferenceVideo, rid).creator_id = matched_id
            if m.end - m.start > cfg.monitoring.max_clip_seconds:
                m.end = m.start + cfg.monitoring.max_clip_seconds
            self._set(rid, "processing", f"Found it at {_hms(m.start)} in \"{vod.title or 'stream'}\". Downloading full quality",
                      vod_url=vod.url, vod_start=m.start, vod_end=m.end, match_confidence=m.confidence)

            lead = 8.0
            section = self.ctx.fetcher.download_section(vod.url, max(0.0, m.start - lead), m.end + 3, work / "section")
            # The download may start at a keyframe before the requested time; re-align on audio for a frame-exact cut.
            local = match.find_in_stream(ref_feats, match.extract_features(section), pad=0.4)
            start, dur = (local.start, local.end - local.start) if local else (min(lead, m.start), m.end - m.start)

            # Keep the full-quality cut until the clip expires so text edits can be re-rendered later.
            clip_dir = self._dir("clips") / f"ref{rid}-{int(now().timestamp())}"
            clip_dir.mkdir(parents=True, exist_ok=True)
            source = clip_dir / f"source{section.suffix or '.mp4'}"
            shutil.move(str(section), source)

            self._set(rid, "processing", "Writing captions")
            # The streamer's name and channel handles (every member's, for a group) help the speech model hear names.
            channels = next((chs for cid, _, chs in candidates if cid == matched_id), [])
            hints = list(dict.fromkeys([creator_name, *filter(None, map(identify.channel_handle, channels))]))
            words, captions_note = self._transcribe(source, start, dur, work, hints)
            stream_date = self._stream_date(vod)
            clean = describe.clean_title(ref_title, creator_name)

            self._set(rid, "processing", "Rendering")
            # Framing (and later edits) are saved with the clip, so a re-render never changes how it looks.
            framing = ClipEdit(start=start, end=start + dur).model_dump()
            renders: dict[str, Path] = {}
            planned = []
            for did, platform, name, handle, st in dest_info:
                fmt_raw = dict(st.get("format") or {})
                ov = lenient(OverlaySettings, st.get("overlay")).model_dump()
                key = json.dumps([fmt_raw, ov], sort_keys=True)
                if key not in renders:
                    renders[key] = self._render(source, clip_dir / f"render-{len(renders)}.mp4", fmt_raw, start, dur, ov, clean, words,
                                                work / f"ov{len(renders)}", framing)
                planned.append((did, platform, st, fmt_raw, ov, renders[key]))

            with self.ctx.db.session() as s:
                clip = Clip(reference_id=rid, creator_id=matched_id, title=clean, edit=framing,
                            vod_url=vod.url, vod_start=m.start, vod_end=m.end, stream_date=stream_date, status="ready",
                            files_dir=str(clip_dir), source_path=str(source), source_start=start, source_duration=dur,
                            words=[w.to_dict() for w in words], captions_note=captions_note,
                            expires_at=now() + timedelta(days=cfg.storage.retention_days))
                s.add(clip)
                s.flush()
                for did, platform, st, fmt_raw, ov, path in planned:
                    info = probe(path)
                    title, desc = describe.build(platform, ref_title, creator_name, st, stream_date)
                    s.add(ClipOutput(clip_id=clip.id, destination_id=did, platform=platform, title=title, description=desc,
                                     video_title=clean, overlay=ov, format=fmt_raw,
                                     file_path=str(path), width=info.width, height=info.height, fps=info.fps, size_bytes=path.stat().st_size))
                audit(s, "clip.ready", "clip", clip.id, {"reference": rid, "destinations": len(dest_info)})
                clip_title, clip_id = clip.title, clip.id
            self._set(rid, "ready", f"Ready to upload to {len(dest_info)} destination(s)" + (f". {captions_note}" if captions_note else ""))
            events.emit(self.ctx, "approvals", f"Clip ready to upload: {clip_title}", body=f"{creator_name}, {len(dest_info)} page(s)",
                        dedupe_key=f"ready:{rid}:{clip_id}", data={"clip_id": clip_id},
                        discord=notify.ready_message(clip_title, creator_name, [(p, n, h) for _, p, n, h, _ in dest_info]))
            return {"status": "ready", "outputs": len(dest_info)}
        except FetchError as e:
            self._set(rid, "failed", f"Download problem: {e}")
            raise  # retried with backoff by the job queue
        except FFmpegError as e:
            return self._stop(rid, "failed", str(e), account, ref_url)
        finally:
            shutil.rmtree(work, ignore_errors=True)

    def _transcribe(self, source: Path, start: float, dur: float, work: Path, hints: list[str]) -> tuple[list[Word], str]:
        """Words spoken in the clip, timed from the clip's start. Captions are skipped (with a note) if this fails.
        A little extra audio is included on both sides so words at the edges aren't cut in half."""
        audio = work / "speech.wav"
        pad_before = min(0.8, start)
        try:
            run(["-ss", f"{start - pad_before:.3f}", "-i", str(source), "-t", f"{dur + pad_before + 0.8:.3f}",
                 "-vn", "-ac", "1", "-ar", "16000", str(audio)])
            raw = self.ctx.transcriber.words(audio, hints)
            shifted = [Word(w.start - pad_before, w.end - pad_before, w.text) for w in raw]
            return overlay.clean_words(shifted, dur), ""
        except (TranscribeError, FFmpegError) as e:
            return [], f"Captions skipped: {e}"
        except Exception as e:
            log.exception("transcription failed")
            return [], f"Captions skipped: speech recognition failed ({type(e).__name__})"

    def _stream_date(self, vod) -> datetime | None:
        if vod.published_at:
            return vod.published_at
        with self.ctx.db.session() as s:
            asset = s.scalar(select(VodAsset).where(VodAsset.url == vod.url))
            if asset and asset.published_at:
                return asset.published_at
        try:
            when = self.ctx.fetcher.vod_details(vod.url).published_at
        except FetchError:
            return None  # the date line is simply left out
        if when:
            with self.ctx.db.session() as s:
                asset = s.scalar(select(VodAsset).where(VodAsset.url == vod.url))
                if asset:
                    asset.published_at = when
        return when

    def _render(self, source: Path, out: Path, fmt_raw: dict, start: float, dur: float, ov: dict, title_text: str,
                words: list[Word], ov_dir: Path, edit: dict | None = None) -> Path:
        """`words` are timed from `start`; an editor `edit` may move the cut, zoom/pan, change speed and add texts."""
        fmt = OutputFormat.from_settings(fmt_raw)
        zoom, pan, speed, texts, video_height = 1.0, (0.5, 0.5), 1.0, [], 0.0  # no edit: a clip from before framing was saved
        if edit:
            video_height = edit.get("video_height", 0)  # edits saved before framing existed were fit to frame
            shift = start - edit["start"]  # words were timed from the original cut
            start, dur = edit["start"], edit["end"] - edit["start"]
            zoom, pan, speed, texts = edit["zoom"], (edit["pan_x"], edit["pan_y"]), edit["speed"], edit["texts"]
            words = [Word((w.start + shift) / speed, (w.end + shift) / speed, w.text) for w in words]
        out_dur = dur / speed
        use_text = bool((ov["title"]["enabled"] and title_text.strip()) or (ov["captions"]["enabled"] and words) or texts)
        if use_text:
            overlay.prepare(ov_dir, overlay.build_ass(fmt.width, fmt.height, ov, title_text, words, out_dur, texts))
        return render(source, out, fmt, start=start, duration=dur, overlay_dir=ov_dir if use_text else None,
                      zoom=zoom, pan=pan, speed=speed, video_height=video_height)

    @staticmethod
    def _render_inputs(o: ClipOutput, clip: Clip) -> str:
        """Everything a re-render depends on, to tell whether a finished render is still the latest wanted."""
        return json.dumps([o.format, o.overlay, o.video_title, clip.words, clip.edit], sort_keys=True, default=str)

    def rerender(self, output_ids: list[int]) -> dict:
        """Re-render outputs after their text or style was edited. Each gets its own new file."""
        done = 0
        for oid in output_ids:
            with self.ctx.db.session() as s:
                o = s.get(ClipOutput, oid)
                clip = s.get(Clip, o.clip_id) if o else None
                if not o or not clip or clip.status != "ready" or not clip.source_path or not Path(clip.source_path).exists():
                    if o:
                        o.render_state, o.render_error = "failed", "The original footage for this clip has expired."
                    continue
                job = (Path(clip.source_path), Path(clip.files_dir), dict(o.format or {}), dict(o.overlay or {}), o.video_title,
                       [Word.from_dict(w) for w in clip.words or []], clip.source_start or 0.0, clip.source_duration or 0.0, o.file_path,
                       dict(clip.edit) if clip.edit else None, self._render_inputs(o, clip))
            source, cdir, fmt_raw, ov, vtitle, words, start, dur, old, edit, inputs = job
            ov = lenient(OverlaySettings, ov).model_dump()
            out = cdir / f"output-{oid}-{int(now().timestamp() * 1000)}.mp4"
            work = self._dir("tmp") / f"rerender-{oid}-{random.randrange(1 << 30)}"
            try:
                self._render(source, out, fmt_raw, start, dur, ov, vtitle, words, work, edit)
                info = probe(out)
                with self.ctx.db.session() as s:
                    o = s.get(ClipOutput, oid)
                    if self._render_inputs(o, s.get(Clip, o.clip_id)) != inputs:
                        # Edited again while this was rendering: a newer job renders the latest, so drop this one.
                        out.unlink(missing_ok=True)
                        continue
                    o.file_path, o.width, o.height, o.fps, o.size_bytes = str(out), info.width, info.height, info.fps, out.stat().st_size
                    o.render_state, o.render_error = "ready", None
                    still_used = s.scalar(select(func.count()).select_from(ClipOutput).where(ClipOutput.file_path == old)) if old else 0
                if old and not still_used:
                    Path(old).unlink(missing_ok=True)
                done += 1
            except FFmpegError as e:
                with self.ctx.db.session() as s:
                    o = s.get(ClipOutput, oid)
                    o.render_state, o.render_error = "failed", str(e)[:300]
            finally:
                shutil.rmtree(work, ignore_errors=True)
        return {"rendered": done}

    # ---------- analytics ----------
    def fetch_metrics(self, output_id: int) -> dict:
        """Read an uploaded post's public numbers (TikTok, YouTube) and store a snapshot."""
        with self.ctx.db.session() as s:
            o = s.get(ClipOutput, output_id)
            if not o or not o.post_url:
                return {"skipped": True}
            url = o.post_url
        post = self.ctx.fetcher.post_details(url)
        with self.ctx.db.session() as s:
            s.add(MetricSnapshot(output_id=output_id, views=post.views, likes=post.likes, comments=post.comments, shares=post.shares))
        return {"views": post.views}

    def refresh_metrics(self) -> dict:
        """Every few hours: refresh numbers for posts uploaded in the last 60 days."""
        since = now() - timedelta(days=60)
        with self.ctx.db.session() as s:
            ids = [o.id for o in s.scalars(select(ClipOutput).where(ClipOutput.post_url.is_not(None), ClipOutput.platform.in_(("tiktok", "youtube")),
                                                                        ClipOutput.uploaded_at >= since)).unique()]
        for i, oid in enumerate(ids):
            self.ctx.jobs.enqueue("metrics.fetch", {"output_id": oid}, max_attempts=2, delay=i * random.uniform(3, 8))
        return {"queued": len(ids)}

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
                    o.file_path, o.status = None, "expired"
                if clip.files_dir:
                    shutil.rmtree(clip.files_dir, ignore_errors=True)  # renders + the kept source cut
                clip.status, clip.source_path = "expired", None
                expired += 1
            vods = 0
            for v in s.scalars(select(VodAsset).where(VodAsset.last_used_at <= cutoff)):
                if v.features_path:
                    Path(v.features_path).unlink(missing_ok=True)
                s.delete(v)
                vods += 1
            # Finished background jobs are only useful for a few days of history.
            s.execute(delete(Job).where(Job.status.in_(("succeeded", "cancelled", "failed")), Job.finished_at <= now() - timedelta(days=7)))
        tmp = self.media / "tmp"
        if tmp.exists():
            for p in tmp.iterdir():
                if datetime.fromtimestamp(p.stat().st_mtime, timezone.utc) < now() - timedelta(hours=12):
                    shutil.rmtree(p, ignore_errors=True) if p.is_dir() else p.unlink(missing_ok=True)
        return {"clips_expired": expired, "streams_forgotten": vods, "events_forgotten": events.cleanup(self.ctx)}


def _hms(sec: float) -> str:
    sec = int(sec)
    return f"{sec // 3600}:{sec % 3600 // 60:02d}:{sec % 60:02d}"


def _link_platform(url: str) -> str:
    return "youtube" if "youtu" in url else "instagram" if "instagram.com" in url else "tiktok"


def register(ctx: Any) -> Pipeline:
    p = Pipeline(ctx)
    ctx.pipeline = p
    q = ctx.jobs
    q.register("monitor.tick", lambda jc, pl: p.tick())
    q.register("source.check", lambda jc, pl: p.check_source(pl["source_id"]))
    q.register("clip.build", lambda jc, pl: p.build_clip(pl["reference_id"], pl.get("vod_url"), pl.get("waits", 0), jc.cancelled))
    q.register("intake.link", lambda jc, pl: p.intake_link(pl["url"], pl.get("creator_id")))
    # Jobs queued by versions before the events log carry a raw message; they're dropped rather than resent.
    q.register("notify.discord", lambda jc, pl: events.deliver(ctx, pl["event_id"]) if "event_id" in pl else {"skipped": "old format"})
    q.register("storage.cleanup", lambda jc, pl: p.cleanup())
    q.register("clip.rerender", lambda jc, pl: p.rerender(pl["output_ids"]))
    q.register("metrics.fetch", lambda jc, pl: p.fetch_metrics(pl["output_id"]))
    q.register("metrics.refresh", lambda jc, pl: p.refresh_metrics())
    q.every("metrics.refresh", 3 * 3600)
    q.every("monitor.tick", 60)
    q.every("storage.cleanup", 6 * 3600)
    q.heavy = {"clip.build", "clip.rerender"}
    return p

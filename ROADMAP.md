# Roadmap

## Vyral 2.0 plan (Nov 2026)

Built into the existing app, phase by phase, each tested before the next.

**What exists to build on.** Desktop shell (Tauri/Rust: window, tray, updates, clipboard pickup) running a local
service (Python/FastAPI, SQLite with migrations, a persistent job queue with retries, cancellation and crash
recovery, secrets in the OS keychain), and a React UI. Video work is deterministic (FFmpeg, local Whisper,
audio-fingerprint matching), sources are read with yt-dlp, Discord is wired for notifications and a phone inbox.
There are no AI model APIs yet, no campaign data, and no social logins (uploads are manual).

| Phase | Status | Notes |
|---|---|---|
| 1. Foundation: Vyral Intelligence, agent activity, events, notification service, dashboard | **Started.** Agents view (real job data), events log, Notification Service (per-category Discord channels, priorities, quiet hours, dedupe, history), Needs your attention | Next: costs per task once AI calls exist |
| 2. Campaign Studio: campaigns, brief import, requirement extraction, compliance, standard and split-screen clipping, QC | Not started | Brief parsing and clip ranking need an AI model (decision below). Split-screen and QC checks that code can do (duration, aspect, loudness, caption timing) need none |
| 3. Campaign Intelligence: scout, scoring, creator and footage matching, recommendations | Not started | No official API found for clippers to list Whop / Content Rewards campaigns; starts with paste-a-brief and paste-a-link import |
| 4. Discord reports and earnings notifications | Partly (Phase 1 service) | Daily/weekly reports next |
| 5. Account intelligence and publishing | Not started | Official publishing needs each platform's app review; manual upload stays the default |
| 6. Autonomous operations | Partly (monitoring, auto clipping, health in Agents) | |
| 7. Business intelligence | Not started | Needs earnings data (manual entry first) |

**Decisions needed from the user:** an AI model provider and monthly budget (needed for Phases 2 and 3), whether to
read Whop's public campaign directory, and whether to pursue platform app reviews for publishing.

**Framing (done):** new clips are zoomed in (the stream fills 60% of the frame's height, centered) and the framing is
saved with each clip; clips made earlier stay fit to frame. Video Editor: Zoomed in / Fit to frame, size, zoom,
left/right, up/down, reset. Subject (face) tracking is not built yet.

## Done (Nov 2026)

1. **Analytics**: after uploading, paste the post link on the clip (Ready to Upload). Vyral reads public views/likes/comments/shares for TikTok and YouTube every few hours (yt-dlp, no login) and stores snapshots; Instagram/Facebook numbers can be typed in. Analytics page: totals, by platform/streamer/page, by clip length, top clips, views over time. Unavailable shown as unavailable, never 0.
2. **Video editor**: opened from the sidebar or "Edit video" on a clip. Trim start/end anywhere in the downloaded footage (drag handles, number fields, or [ and ] at the playhead), zoom + pan, speed 0.5x to 2x, up to 20 timed text overlays, live 9:16 preview (canvas-blurred background, title, synced captions, texts), undo/redo (Cmd/Ctrl+Z, Shift+Cmd+Z). Save re-renders every page's video. Edit stored on the clip (`clips.edit`), caption words re-timed from the trim and speed.

Done this round: real platform logos, Kick stream channels, one clipping account covering several streamers, auto-updates via Drewzyy/vyral-releases (latest.json).

## 0.2.0: Vyral (done)

| Feature | Status |
|---|---|
| Watch TikTok / YouTube Shorts accounts, baseline on first check, backoff on errors | Tested (simulated TikTok; live TikTok not reachable from the build sandbox) |
| Find the moment in the creator's streams by audio (jump cuts, music overlays) | Tested on real audio pipelines with synthetic speech |
| Full-quality section download + frame-exact re-alignment + vertical render | Tested (real FFmpeg; downloads simulated) |
| Per-destination captions and titles | Tested |
| Ready to Upload: preview, copy, save to Downloads, mark uploaded | Tested (E2E) |
| Discord notifications | Tested against a simulated Discord |
| 30-day auto-delete | Tested |
| Mac + Windows installers, start at login, tray, service watchdog | Built by CI; watchdog tested; **not yet run by a person on a real Mac/PC** |

Next up: burned-in word-synced captions (Video Editor), Intel Mac build, signed installers (needs paid certificates), auto-update.


Status key: **Tested** (works, covered by automated tests) · **Implemented** (works, not fully automated-tested) · **Needs your authorization** (code done, needs a real login or platform approval to verify) · **In development** · **Not started** · **Blocked**

## Milestone 1: Foundation (done)

| Feature | Status |
|---|---|
| Local backend, SQLite + migrations, structured logs with secret redaction | Tested |
| Dark design system, sidebar navigation, ⌘1–9 shortcuts | Tested (E2E) |
| Dashboard from real data, unavailable vs zero distinguished | Tested |
| Source accounts: add by handle/URL, CSV/paste import, creators, folders, filters, bulk actions, pause/resume | Tested |
| Destination accounts: planned drafts, per-account settings with validation | Tested |
| Account funnel: drag-and-drop routes, cross-creator confirmation, auto-route by creator, routing preview, persisted layout | Tested (E2E) |
| Persistent settings (budgets, models, privacy, processing, storage) | Tested |
| Persistent job queue: retries, backoff, idempotency, cancel, crash recovery | Tested |
| Keychain secret store (encrypted file fallback) | Implemented (Keychain path untested: no Mac in CI) |
| TikTok connect (Login Kit Desktop, hex PKCE) as destination or owned source | Tested against mocked TikTok; **needs your authorization** |
| Facebook + Instagram connect (one login, all Pages + linked IG) | Tested against mocked Graph API; **needs your authorization** |
| Token refresh job, expiry warnings, disconnect with revoke | Tested |
| Tauri macOS shell (sidecar, tray, hide-on-close, single instance) | Compiles; **not yet run on a Mac** |
| Sidecar packaging (PyInstaller, migrations bundled) | Tested on Linux; Mac build untested |

## Milestone 2: Video library and processing (next)

Not started. Plan, in order:
1. `media_assets` table, content-hash dedupe (BLAKE3), immutable originals, drag-and-drop import with size/type validation (ffprobe sniffing, not extensions).
2. FFmpeg in a sandboxed subprocess (no network, timeout, resource limits): metadata, thumbnails, proxy previews.
3. Local transcription with faster-whisper (word timestamps), cached by audio hash.
4. Library UI with previews, filters, storage usage and cleanup.

## Milestone 3: Video editor

First version done (see above). Still to do: split/multiple segments, autosave drafts, presets. Non-destructive edit list (JSON timeline) rendered by FFmpeg; preview in the webview with canvas compositing for the blurred background and captions. Word-synced captions (orange emphasis / white base default preset). Undo/redo via command stack, autosave with versioned snapshots.

## Milestone 4: AI clipping and VOD matching

Not started. Matching pipeline: transcript n-gram search → audio fingerprint (chromaprint) alignment → visual embedding check → boundary refinement. Confidence reported per signal; nothing below threshold is called a match. Moment detection from transcript + audio features + cheap LLM pass, ranked candidates.

## Milestone 5: Discovery and integrations

Not started. TikTok oEmbed for reference URLs, Display API video lists + metrics for accounts you authorize, YouTube Data API for channels, Twitch Helix for VOD metadata, monitoring scheduler.

## Milestone 6: Publishing

Not started. Approval queue, scheduling, idempotent publish per (asset, destination), retries, resumable uploads (YouTube resumable, TikTok chunked, Meta rupload).

## Milestone 7: Analytics and learning

Not started. Metrics snapshots, predicted vs actual, pattern reports, training dataset export, versioned models with evaluation and rollback.

## Milestone 8: Production readiness

Not started. Signed + notarized Mac build, auto-update, security audit, load and recovery testing.

## Prioritized next tasks

1. Build and launch the .app on your Mac (`scripts/build-mac-app.sh`), confirm Keychain and system-browser login.
2. Register the three developer apps and connect one real account each (the app guides you).
3. Milestone 2 step 1: media import + hashing.

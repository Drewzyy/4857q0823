# Roadmap

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
| YouTube connect (Google OAuth, PKCE, loopback) | Tested against mocked Google; **needs your authorization** to verify live |
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

Not started. Non-destructive edit list (JSON timeline) rendered by FFmpeg; preview in the webview with canvas compositing for the blurred background and captions. Word-synced captions (orange emphasis / white base default preset). Undo/redo via command stack, autosave with versioned snapshots.

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

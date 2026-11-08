# Architecture

## Shape

```
macOS app (Tauri, Rust)                    ~200 lines. Starts the backend, hosts the window,
  │  spawns sidecar, waits for /api/health   menu bar icon, keeps running when the window closes.
  ▼
clippr-backend (Python 3.11+, FastAPI)     Bound to 127.0.0.1 only.
  ├─ REST API (/api/*)                     Token + Host + Origin checked on every call.
  ├─ OAuth callback (/oauth/callback/*)    Loopback redirect target for platform logins.
  ├─ Job queue + worker threads            SQLite-backed, survives crashes.
  ├─ Platform connectors                   youtube / tiktok / meta (more plug in the same way).
  ├─ SQLite (WAL) + Alembic migrations     ~/Library/Application Support/<app>/clippr.db
  └─ Secret store                          macOS Keychain (encrypted-file fallback off-Mac).
  ▲
React + TypeScript UI (Vite)               Served by the backend. No native IPC access.
```

## Decisions

| Decision | Why | Rejected |
|---|---|---|
| Tauri over Electron | Native WKWebView (hardware HEVC/H.264 decode on Mac), ~10 MB shell vs ~150 MB, strict capability model. | Electron: heavier, bundles Chromium. |
| Python backend as sidecar | Best ecosystem for the hard parts coming next: faster-whisper, audio fingerprinting, OpenCV, model inference. FFmpeg via subprocess. | Node backend: weak ML story. Rust backend: slow to iterate on ML. |
| SQLite + WAL locally | Zero setup, crash-safe, fast. SQLAlchemy keeps a Postgres path open for a hosted version. | Postgres locally: needless daemon. |
| SQLite job queue, no Redis | One user, one machine. Compare-and-set claim, retries, idempotency keys and crash recovery cover what Redis would. Swappable later. | Redis + Celery: extra processes to install and babysit. |
| UI served by backend, not bundled into Tauri | One code path for dev, browser and desktop. Token injected into the HTML at serve time. The webview gets zero native permissions. | Tauri IPC: more attack surface for no gain. |
| Backend opens OAuth in the system browser | Users log in where their password manager and existing sessions live. No embedded login webviews. | Embedded webview login: platforms discourage it, and it could see credentials. |

## Data model (Milestone 1)

`creators`, `folders`, `source_accounts`, `destination_accounts`, `connections`, `funnel_routes`, `settings`, `jobs`, `audit_log`. Tokens and app secrets are never in the database, only in the secret store, keyed by `oauth:<platform>:<user id>`, `app:<platform>`, `account:<platform>:<id>`.

Planned tables (designed, not created yet): `media_assets` (content-hashed, immutable originals), `transcripts`, `fingerprints`, `embeddings`, `reference_videos`, `vod_matches`, `clip_candidates`, `projects` + `project_versions` (non-destructive edit lists), `publications` (idempotency key per destination+asset), `metrics_snapshots`, `ai_calls` (cost ledger), `model_versions`.

## Funnel invariant

A route between accounts of two different creators exists only if the user confirmed it. If a creator is reassigned later, the route is kept but paused (`blocked`) instead of silently mixing content. `routing.resolve_destinations()` is the single function the publishing queue will use.

## Connector contract

`platforms/base.py: OAuthConnector` exposes `authorize_url`, `exchange_code`, `refresh`, `identities`, `validate_app`, `revoke`, plus setup steps for the wizard. Publishing and metrics adapters will hang off the same classes. Adding a platform is one file plus a registry entry.

## Agents (planned, Milestone 4+)

The clipping agent and research agent will be separate job kinds that only talk through tables (clip candidates, metrics, pattern reports), not through each other's code. That keeps them independently testable and replaceable.

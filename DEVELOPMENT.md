# Development

## Requirements

Python 3.11+, Node 20+, FFmpeg. For the Mac app: Rust (stable), Xcode Command Line Tools.

## Layout

```
backend/clippr/        FastAPI app, models, connectors, job queue
  api/                 HTTP routes (accounts, funnel, connections, system)
  platforms/           youtube.py, tiktok.py, meta.py, urls.py, base.py
  migrations/          Alembic (runs automatically at startup)
backend/tests/         pytest
frontend/src/          React UI (pages/, components/, lib/api.ts, styles/app.css)
frontend/e2e/          Playwright tests
desktop/src-tauri/     macOS shell
relay/                 optional HTTPS OAuth relay page (Meta fallback)
scripts/               build scripts
```

## Run

```bash
cd backend && pip install -e ".[dev]"
cd ../frontend && npm install

# Option A: one process, built UI
cd frontend && npm run build && cd ../backend && python -m clippr          # http://127.0.0.1:8765

# Option B: hot reload
cd backend && CLIPPR_API_TOKEN=dev python -m clippr
cd frontend && VITE_CLIPPR_TOKEN=dev npm run dev                            # http://127.0.0.1:5173
```

Useful env vars: `CLIPPR_DATA_DIR` (default `~/Library/Application Support/AI Clipper`), `CLIPPR_PORT` (8765), `CLIPPR_SECRET_BACKEND` (`auto|keychain|file|memory`), `CLIPPR_NO_WORKER=1`.

Keep port 8765 unless you re-register the Meta redirect; Google and TikTok accept any loopback port.

## Mac app

```bash
./scripts/build-mac-app.sh          # frontend build -> PyInstaller sidecar -> tauri build
cd desktop && npx tauri dev         # dev shell (needs a sidecar built first)
```

## Schema changes

```bash
cd backend
python - <<'PY'
from alembic import command; from alembic.config import Config; from sqlalchemy import create_engine
c = Config(); c.set_main_option("script_location", "clippr/migrations")
with create_engine("sqlite:////tmp/clippr-dev.db").begin() as conn:
    c.attributes["connection"] = conn; command.upgrade(c, "head")
    command.revision(c, message="describe change", autogenerate=True)
PY
```

## Conventions

- Unavailable data is `null` in the API and a dash in the UI. Never `0`.
- Unbuilt sections show their planned scope and no controls.
- Secrets only through `ctx.secrets`. Never log, return or store them in the DB.
- User-facing errors: `ApiError` / `PlatformError` with a plain-English message.

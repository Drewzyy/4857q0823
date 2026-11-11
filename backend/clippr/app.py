"""FastAPI application factory."""
from __future__ import annotations

import hmac
import html
import logging
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
from starlette.exceptions import HTTPException as StarletteHTTPException

from .api import accounts, analytics, clips, inbox, library, longform, notifications, streamers, system, updates
from .api.system import load_settings
from .fetch import Fetcher, YtDlpFetcher
from .media.transcribe import Transcriber, WhisperTranscriber
from .api.deps import ApiError
from .config import Config
from .db import Database
from . import net
from .jobs import JobQueue
from .logging_setup import setup_logging
from .secrets_store import SecretStore, make_store

log = logging.getLogger("clippr.app")

CSP = ("default-src 'self'; img-src 'self' data: blob: https:; media-src 'self' blob:; style-src 'self' 'unsafe-inline'; "
       "script-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")


@dataclass
class AppContext:
    config: Config
    db: Database
    secrets: SecretStore
    jobs: JobQueue
    fetcher: Fetcher = None  # type: ignore[assignment]
    transcriber: Transcriber = None  # type: ignore[assignment]
    pipeline: Any = None
    inbox: Any = None


def build_context(config: Config, secrets: SecretStore | None = None, fetcher=None, transcriber=None) -> AppContext:
    config.ensure_dirs()
    setup_logging(config.data_dir / "logs")
    database = Database(f"sqlite:///{config.db_path}")
    database.migrate()
    ctx = AppContext(config=config, db=database, secrets=secrets or make_store(config.secret_backend, config.data_dir),
                     jobs=JobQueue(database))
    ctx.fetcher = fetcher or YtDlpFetcher()
    def caption_settings() -> tuple[str, str]:
        with database.session() as s:
            c = load_settings(s).captions
            return c.accuracy, c.language

    ctx.transcriber = transcriber or WhisperTranscriber(config.data_dir / "models", caption_settings)
    from .pipeline import register

    register(ctx)
    from .discord_inbox import DiscordInbox

    ctx.inbox = DiscordInbox(ctx)

    def heavy_limit() -> int:
        with database.session() as s:
            return load_settings(s).processing.max_concurrent_jobs

    ctx.jobs.heavy_limit = heavy_limit
    from . import fetch
    fetch.on_progress = ctx.jobs.beat
    return ctx


def create_app(config: Config | None = None, ctx: AppContext | None = None) -> FastAPI:
    ctx = ctx or build_context(config or Config())
    cfg = ctx.config
    @asynccontextmanager
    async def lifespan(_: FastAPI):
        if cfg.run_worker:
            # Room for the most clips the settings allow (4) plus monitoring, link intake and notifications alongside;
            # how many clips build at once is limited separately (Settings), so extra workers just wait.
            ctx.jobs.online = net.online  # downloads wait while there's no internet
            ctx.jobs.start(workers=7)
            ctx.inbox.start()
            ctx.jobs.enqueue("clips.restore", {}, max_attempts=1)  # brings back page videos a past update lost
        yield
        ctx.inbox.stop()
        ctx.jobs.stop()

    app = FastAPI(title="Vyral", version="0.1.0", docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan)
    app.state.ctx = ctx
    app.state.ui_served = False
    allowed_hosts = {f"127.0.0.1:{cfg.port}", f"localhost:{cfg.port}", "127.0.0.1", "localhost", "testserver"}

    @app.middleware("http")
    async def security(request: Request, call_next):
        # DNS-rebinding defence: only answer requests addressed to the loopback host.
        if request.headers.get("host", "") not in allowed_hosts:
            return JSONResponse({"error": {"code": "bad_host", "message": "Forbidden host"}}, status_code=421)
        path = request.url.path
        if path.startswith("/api/") and path != "/api/health":
            token = request.headers.get("x-clippr-token", "")
            if not token and path.startswith("/api/media/") and request.method == "GET":
                token = request.query_params.get("t", "")
            if not hmac.compare_digest(token.encode(), cfg.api_token.encode()):
                return JSONResponse({"error": {"code": "unauthorized", "message": "Missing or invalid app token"}}, status_code=401)
        if request.method in ("POST", "PUT", "PATCH", "DELETE"):
            origin = request.headers.get("origin")
            if origin and origin.replace("http://", "") not in allowed_hosts and not origin.startswith("tauri://"):
                return JSONResponse({"error": {"code": "bad_origin", "message": "Cross-origin request blocked"}}, status_code=403)
        resp: Response = await call_next(request)
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        resp.headers.setdefault("Referrer-Policy", "no-referrer")
        resp.headers.setdefault("X-Frame-Options", "DENY")
        if path.startswith("/api/"):
            resp.headers.setdefault("Cache-Control", "no-store")
        return resp

    @app.exception_handler(ApiError)
    async def api_error(_: Request, e: ApiError):
        return JSONResponse({"error": {"code": e.code, "message": e.message, **e.extra}}, status_code=e.status)

    @app.exception_handler(RequestValidationError)
    async def validation_error(_: Request, e: RequestValidationError):
        first = e.errors()[0] if e.errors() else {"loc": [], "msg": "Invalid request"}
        field_name = ".".join(str(x) for x in first.get("loc", [])[1:]) or "request"
        return JSONResponse({"error": {"code": "validation", "message": f"{field_name}: {first.get('msg')}"}}, status_code=422)

    @app.exception_handler(StarletteHTTPException)
    async def http_error(_: Request, e: StarletteHTTPException):
        return JSONResponse({"error": {"code": "http_error", "message": str(e.detail)}}, status_code=e.status_code)

    @app.exception_handler(Exception)
    async def unhandled(_: Request, e: Exception):
        log.exception("unhandled error")
        return JSONResponse({"error": {"code": "internal", "message": "Something went wrong. Details are in the app log."}}, status_code=500)

    for r in (accounts.router, streamers.router, library.router, longform.router, system.router, clips.router, updates.router, analytics.router, inbox.router, notifications.router):
        app.include_router(r, prefix="/api")

    dist = cfg.frontend_dist
    if dist and (dist / "index.html").exists():
        index_html = (dist / "index.html").read_text()
        token_tag = f'<meta name="clippr-token" content="{html.escape(cfg.api_token)}">'

        def serve_index() -> HTMLResponse:
            app.state.ui_served = True  # lets the installer test confirm the window really loaded the UI
            return HTMLResponse(index_html.replace("<!--CLIPPR_TOKEN-->", token_tag),
                                headers={"Content-Security-Policy": CSP, "Cache-Control": "no-store"})

        @app.get("/{full_path:path}", include_in_schema=False)
        def spa(full_path: str):
            if full_path.startswith("api/"):
                raise ApiError(404, "not_found", "Not found")
            candidate = (dist / full_path).resolve()
            if full_path and candidate.is_file() and dist.resolve() in candidate.parents:
                return FileResponse(candidate, headers={"Cache-Control": "public, max-age=31536000, immutable"} if "/assets/" in f"/{full_path}" else None)
            return serve_index()

    return app

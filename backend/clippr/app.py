"""FastAPI application factory."""
from __future__ import annotations

import hmac
import html
import json
import logging
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, Response
from starlette.exceptions import HTTPException as StarletteHTTPException

from .api import accounts, clips, connections as connections_api, funnel, system
from .api.system import load_settings
from .fetch import YtDlpFetcher
from .media.transcribe import WhisperTranscriber
from .api.deps import ApiError
from .config import Config
from .connections import CALLBACK_PAGE, ConnectionService
from .db import Database
from .jobs import JobQueue
from .logging_setup import setup_logging
from .platforms import CONNECTORS
from .platforms.base import PlatformError
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
    bundled_apps: dict[str, Any] = field(default_factory=dict)
    connections: ConnectionService = None  # type: ignore[assignment]
    fetcher: Any = None
    transcriber: Any = None
    pipeline: Any = None


def _load_bundled_apps(config: Config) -> dict[str, Any]:
    """Optional platform_apps.json shipped with a build, so end users never see developer consoles."""
    for p in (config.data_dir / "platform_apps.json", Path(__file__).parent / "platform_apps.json"):
        if p.exists():
            try:
                data = json.loads(p.read_text())
                return {k: v for k, v in data.items() if k in CONNECTORS and isinstance(v, dict)}
            except ValueError:
                log.warning("ignoring malformed %s", p.name)
    return {}


def build_context(config: Config, secrets: SecretStore | None = None, http_factory=None, fetcher=None, transcriber=None) -> AppContext:
    config.ensure_dirs()
    setup_logging(config.data_dir / "logs")
    database = Database(f"sqlite:///{config.db_path}")
    database.migrate()
    ctx = AppContext(config=config, db=database, secrets=secrets or make_store(config.secret_backend, config.data_dir),
                     jobs=JobQueue(database), bundled_apps=_load_bundled_apps(config))
    ctx.connections = ConnectionService(ctx, http_factory)
    ctx.jobs.register("connections.refresh_due", lambda jc, p: ctx.connections.refresh_due())
    ctx.jobs.every("connections.refresh_due", 600)
    ctx.fetcher = fetcher or YtDlpFetcher()
    def caption_settings() -> tuple[str, str]:
        with database.session() as s:
            c = load_settings(s).captions
            return c.accuracy, c.language

    ctx.transcriber = transcriber or WhisperTranscriber(config.data_dir / "models", caption_settings)
    from .pipeline import register

    register(ctx)

    def heavy_limit() -> int:
        with database.session() as s:
            return load_settings(s).processing.max_concurrent_jobs

    ctx.jobs.heavy_limit = heavy_limit
    return ctx


def create_app(config: Config | None = None, ctx: AppContext | None = None) -> FastAPI:
    ctx = ctx or build_context(config or Config())
    cfg = ctx.config
    @asynccontextmanager
    async def lifespan(_: FastAPI):
        if cfg.run_worker:
            ctx.jobs.start(workers=3)
        yield
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

    for r in (accounts.router, funnel.router, system.router, connections_api.router, clips.router):
        app.include_router(r, prefix="/api")

    def oauth_callback(platform: str, request: Request):
        if platform not in CONNECTORS:
            raise ApiError(404, "not_found", "Unknown platform")
        params = {k: v for k, v in request.query_params.items()}
        try:
            attempt = ctx.connections.complete(platform, params)
            ok, msg = attempt.status == "succeeded", attempt.message
        except PlatformError as e:
            ok, msg = False, str(e)
        page = CALLBACK_PAGE.format(
            color="#16a34a33" if ok else "#dc262633", icon="✓" if ok else "!",
            title="Connected" if ok else "Couldn't connect",
            message=html.escape(msg + (" You can close this tab and go back to Vyral." if ok else "")),
        )
        return HTMLResponse(page, headers={"Content-Security-Policy": "default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline'"})

    app.add_api_route("/oauth/callback/{platform}", oauth_callback, methods=["GET"], include_in_schema=False)
    app.add_api_route("/oauth/callback/{platform}/", oauth_callback, methods=["GET"], include_in_schema=False)

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
            if full_path.startswith(("api/", "oauth/")):
                raise ApiError(404, "not_found", "Not found")
            candidate = (dist / full_path).resolve()
            if full_path and candidate.is_file() and dist.resolve() in candidate.parents:
                return FileResponse(candidate, headers={"Cache-Control": "public, max-age=31536000, immutable"} if "/assets/" in f"/{full_path}" else None)
            return serve_index()

    return app

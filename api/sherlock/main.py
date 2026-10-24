"""FastAPI app (TRD §3.1). Run with one worker: the job runner and SSE bus live in-process."""

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import APIRouter, Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse

from sherlock import __version__
from sherlock.config import Settings, get_settings
from sherlock.db.connection import connect
from sherlock.db.migrate import current_version, migrate
from sherlock.errors import RequestIdMiddleware, install_error_handlers, not_found
from sherlock.identity import IdentityMiddleware, current_user
from sherlock.llm.models import LLMReachability, validate_model_roles
from sherlock.ratelimit import RateLimiter, rate_limit
from sherlock.routers import datasets, me, steps
from sherlock.storage import VersionConnections
from sherlock.storage_check import check_storage


def _db_status(settings: Settings) -> dict:
    try:
        conn = connect(settings)
        try:
            return {"ok": True, "schema_version": current_version(conn)}
        finally:
            conn.close()
    except Exception:
        return {"ok": False, "schema_version": None}


def create_app() -> FastAPI:
    settings = get_settings()

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        validate_model_roles(settings)  # startup fails on a non-NVIDIA role (TRD §3.5)
        app.state.storage = check_storage(settings)
        conn = connect(settings)
        try:
            migrate(conn)
        finally:
            conn.close()
        yield
        app.state.duckdb.close()

    app = FastAPI(title="Sherlock", version=__version__, lifespan=lifespan)
    app.state.settings = settings
    app.state.llm_reachability = LLMReachability(settings)
    app.state.rate_limiter = RateLimiter()
    app.state.storage = {}
    app.state.duckdb = VersionConnections(settings)
    install_error_handlers(app)

    # Added inner to outer: identity runs inside the request-ID scope; CORS is outermost.
    app.add_middleware(IdentityMiddleware, settings=settings)
    app.add_middleware(RequestIdMiddleware)
    if settings.cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=[o.strip() for o in settings.cors_origins.split(",") if o.strip()],
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    @app.get("/healthz", tags=["ops"])
    def healthz() -> dict:
        db = _db_status(settings)
        storage = app.state.storage
        return {
            "ok": db["ok"] and storage.get("writable", False) and storage.get("sqlite_lock", False),
            "version": __version__,
            "db": db,
            "storage": storage,
            "llm": {"reachable": app.state.llm_reachability.check()},
            "models": settings.models,
        }

    # Every /api/v1 route depends on the cookie user and the per-user rate limit (TRD §3.1, §15).
    api = APIRouter(prefix="/api/v1", dependencies=[Depends(current_user), Depends(rate_limit)])
    api.include_router(me.router)
    api.include_router(datasets.router)
    api.include_router(steps.router)
    app.include_router(api)
    if settings.web_dist_dir and settings.web_dist_dir.is_dir():
        _serve_web(app, settings.web_dist_dir)
    return app


def _serve_web(app: FastAPI, dist: Path) -> None:
    """Serve the built web app under / with a single-page-app fallback to index.html."""
    root = dist.resolve()
    index = root / "index.html"

    @app.get("/{path:path}", include_in_schema=False)
    def web(path: str):
        if path.startswith("api/"):
            raise not_found()  # unknown API routes stay JSON, never the web app
        candidate = (root / path).resolve()
        if path and candidate.is_file() and candidate.is_relative_to(root):
            return FileResponse(candidate)
        return FileResponse(index)


app = create_app()

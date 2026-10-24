"""FastAPI app (TRD §3.1). Run with one worker: the job runner and SSE bus live in-process."""

from fastapi import APIRouter, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from sherlock import __version__
from sherlock.config import get_settings


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title="Sherlock", version=__version__)

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
        # DB and LLM reachability join this response when those layers land (TRD §11).
        return {"ok": True, "version": __version__, "models": settings.models}

    api = APIRouter(prefix="/api/v1")
    app.include_router(api)
    return app


app = create_app()

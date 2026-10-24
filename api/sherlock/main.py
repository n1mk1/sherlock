"""FastAPI app (TRD §3.1). Run with one worker: the job runner and SSE bus live in-process."""

from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from sherlock import __version__
from sherlock.config import get_settings
from sherlock.llm.models import LLMReachability, validate_model_roles


def create_app() -> FastAPI:
    settings = get_settings()
    llm_reachability = LLMReachability(settings)

    @asynccontextmanager
    async def lifespan(_: FastAPI):
        validate_model_roles(settings)  # startup fails on a non-NVIDIA role (TRD §3.5)
        yield

    app = FastAPI(title="Sherlock", version=__version__, lifespan=lifespan)
    app.state.llm_reachability = llm_reachability

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
        # DB reachability joins this response with the migrations (TRD §11).
        return {
            "ok": True,
            "version": __version__,
            "llm": {"reachable": app.state.llm_reachability.check()},
            "models": settings.models,
        }

    api = APIRouter(prefix="/api/v1")
    app.include_router(api)
    return app


app = create_app()

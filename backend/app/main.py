"""Investigative AI Training Arena - FastAPI entry point."""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.agents.cache import install_cache
from app.agents.candidates import CandidateRegistry
from app.api.routes import Services, public, router
from app.auth import UserStore
from app.config import Settings, get_settings
from app.scenarios.engine import ScenarioEngine
from app.store import Store


@asynccontextmanager
async def _lifespan(app: FastAPI):
    # Installed at server start (not at import) so the test suite's fake models never hit a process-wide cache.
    path = getattr(app.state, "llm_cache_path", None)
    app.state.llm_cache = install_cache(path) if path else None
    yield


def create_app(settings: Settings | None = None, persist: bool = True) -> FastAPI:
    settings = settings or get_settings()
    app = FastAPI(title="Investigative AI Training Arena", version="0.1.0", lifespan=_lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
        allow_methods=["*"],
        allow_headers=["*"],
    )
    # Persist every model response so replays, repeats and re-runs are served from disk (real app only, not tests).
    app.state.llm_cache_path = settings.data_dir / "llm_cache.sqlite" if (persist and settings.llm_cache) else None
    app.state.llm_cache = None
    app.state.services = Services(
        engine=ScenarioEngine(),
        registry=CandidateRegistry(settings),
        store=Store(settings.data_dir if persist else None),
        users=UserStore(settings.data_dir if persist else None, settings.admin_user, settings.admin_password, settings.secret_key),
    )
    app.include_router(public)
    app.include_router(router)
    return app


app = create_app()

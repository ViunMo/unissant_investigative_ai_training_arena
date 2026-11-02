"""Investigative AI Training Arena - FastAPI entry point."""
from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.agents.candidates import CandidateRegistry
from app.api.routes import Services, router
from app.config import Settings, get_settings
from app.scenarios.engine import ScenarioEngine
from app.store import Store


def create_app(settings: Settings | None = None, persist: bool = True) -> FastAPI:
    settings = settings or get_settings()
    app = FastAPI(title="Investigative AI Training Arena", version="0.1.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.state.services = Services(
        engine=ScenarioEngine(),
        registry=CandidateRegistry(settings),
        store=Store(settings.data_dir if persist else None),
    )
    app.include_router(router)
    return app


app = create_app()

from __future__ import annotations

from fastapi import FastAPI
from apps.api.config import load_settings
from apps.api.routes import projects, runs, run_events, skills, artifacts, auth
from core.run_engine import RunEngine
from memory import store


def create_app() -> FastAPI:
    settings = load_settings()

    app = FastAPI(title="API Randarc-Astra", version="0.1.0")

    store.init(settings.data_dir, settings.base_dir / "memory" / "migrations")

    app.state.engine = RunEngine(settings.base_dir)
    app.state.base_dir = settings.base_dir
    app.state.data_dir = settings.data_dir

    app.include_router(projects.router)
    app.include_router(runs.router)
    app.include_router(run_events.router)
    app.include_router(skills.router)
    app.include_router(artifacts.router)
    app.include_router(auth.router)

    return app


app = create_app()

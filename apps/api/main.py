from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from apps.api.config import load_settings
from apps.api.routes import projects, runs, run_events, skills, artifacts, auth, secrets, memory, reminders
from core.run_engine import RunEngine
from core.reminders.scheduler import start_reminder_scheduler
from memory import store


def create_app() -> FastAPI:
    settings = load_settings()

    app = FastAPI(title="API Randarc-Astra", version="0.1.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            "tauri://localhost",
            "http://localhost:5173",
            "http://127.0.0.1:5173",
        ],
        allow_credentials=False,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type"],
    )

    store.init(settings.data_dir, settings.base_dir / "memory" / "migrations")

    app.state.engine = RunEngine(settings.base_dir)
    app.state.base_dir = settings.base_dir
    app.state.data_dir = settings.data_dir
    app.state.reminder_scheduler = start_reminder_scheduler()

    app.include_router(projects.router)
    app.include_router(runs.router)
    app.include_router(run_events.router)
    app.include_router(skills.router)
    app.include_router(artifacts.router)
    app.include_router(secrets.router)
    app.include_router(memory.router)
    app.include_router(reminders.router)
    app.include_router(auth.router)

    return app


app = create_app()

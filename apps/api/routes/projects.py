from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from apps.api.auth import require_auth
from apps.api.models import ProjectCreate, ProjectUpdate
from memory import store

router = APIRouter(prefix="/api/v1/projects", tags=["projects"], dependencies=[Depends(require_auth)])


@router.post("")
def create_project(payload: ProjectCreate):
    settings = payload.settings
    if not settings:
        settings = {
            "llm": {
                "provider": "openai",
                "base_url": "https://api.openai.com/v1",
                "model": "gpt-4.1",
            }
        }
    project = store.create_project(payload.name, payload.tags, settings)
    return project


@router.get("")
def list_projects():
    return store.list_projects()


@router.get("/{project_id}")
def get_project(project_id: str):
    project = store.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Проект не найден")
    return project


@router.put("/{project_id}")
def update_project(project_id: str, payload: ProjectUpdate):
    project = store.update_project(project_id, payload.name, payload.tags, payload.settings)
    if not project:
        raise HTTPException(status_code=404, detail="Проект не найден")
    return project


@router.get("/{project_id}/memory/search")
def search_memory(project_id: str, q: str = "", type: str | None = None, from_ts: str | None = None, to_ts: str | None = None, tags: str | None = None):
    project = store.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Проект не найден")
    return store.search_memory(project_id, q, type, from_ts, to_ts, tags)


@router.get("/{project_id}/runs")
def list_runs(project_id: str, limit: int = 50):
    project = store.get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Проект не найден")
    return store.list_runs(project_id, limit=limit)

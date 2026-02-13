from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request

from apps.api.auth import require_auth

router = APIRouter(prefix="/api/v1/skills", tags=["skills"], dependencies=[Depends(require_auth)])


def _get_registry(request: Request):
    engine = request.app.state.engine
    return engine.registry


@router.get("")
def list_skills(request: Request):
    registry = _get_registry(request)
    return [m.__dict__ for m in registry.list_manifests()]


@router.get("/{skill_name}/manifest")
def get_manifest(skill_name: str, request: Request):
    registry = _get_registry(request)
    manifest = registry.get_manifest(skill_name)
    if not manifest:
        raise HTTPException(status_code=404, detail="Навык не найден")
    return manifest.__dict__


@router.post("/reload")
def reload_skills(request: Request):
    registry = _get_registry(request)
    registry.reload()
    return {"status": "перезагружено", "count": len(registry.list_manifests())}

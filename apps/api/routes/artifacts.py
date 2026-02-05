from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException, Depends
from fastapi.responses import FileResponse

from memory import store

from apps.api.auth import require_auth

router = APIRouter(prefix="/api/v1", tags=["artifacts"], dependencies=[Depends(require_auth)])


@router.get("/artifacts/{artifact_id}/download")
def download_artifact(artifact_id: str):
    artifact = store.get_artifact(artifact_id)
    if not artifact:
        raise HTTPException(status_code=404, detail="Артефакт не найден")

    path = Path(artifact["content_uri"])
    if not path.exists():
        raise HTTPException(status_code=404, detail="Файл артефакта не найден")

    return FileResponse(str(path), filename=path.name)

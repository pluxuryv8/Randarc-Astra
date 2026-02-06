from __future__ import annotations

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from apps.api.auth import require_auth
from core import secrets

router = APIRouter(prefix="/api/v1", tags=["secrets"], dependencies=[Depends(require_auth)])


class UnlockPayload(BaseModel):
    passphrase: str


class OpenAIPayload(BaseModel):
    api_key: str


@router.post("/secrets/unlock")
def unlock(payload: UnlockPayload):
    secrets.set_runtime_passphrase(payload.passphrase)
    return {"status": "ok"}


@router.post("/secrets/openai")
def set_openai(payload: OpenAIPayload):
    secrets.set_runtime_secret("OPENAI_API_KEY", payload.api_key)
    return {"status": "ok"}


@router.post("/secrets/openai_local")
def set_openai_local(payload: OpenAIPayload):
    secrets.set_local_secret("OPENAI_API_KEY", payload.api_key)
    secrets.set_runtime_secret("OPENAI_API_KEY", payload.api_key)
    return {"status": "ok", "stored": True}


@router.get("/secrets/openai_local")
def get_openai_local():
    value = secrets.get_local_secret("OPENAI_API_KEY")
    return {"stored": bool(value)}


@router.get("/secrets/status")
def status():
    return {"vault_unlocked": bool(secrets.get_runtime_passphrase())}

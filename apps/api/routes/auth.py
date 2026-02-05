from __future__ import annotations

from fastapi import APIRouter

from apps.api.auth import bootstrap_token
from apps.api.models import BootstrapRequest
from memory import store

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


@router.get("/status")
def auth_status():
    return {"initialized": bool(store.get_session_token_hash())}


@router.post("/bootstrap")
def auth_bootstrap(payload: BootstrapRequest):
    return bootstrap_token(payload.token)

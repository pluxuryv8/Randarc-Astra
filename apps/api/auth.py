from __future__ import annotations

import hashlib
import hmac
import os

from fastapi import HTTPException, Request, status

from memory import store


def _hash_token(token: str, salt: str) -> str:
    return hashlib.sha256((salt + token).encode("utf-8")).hexdigest()


def _ensure_salt() -> str:
    return os.urandom(16).hex()


def require_auth(request: Request) -> None:
    token = None
    auth_header = request.headers.get("Authorization")
    if auth_header and auth_header.startswith("Bearer "):
        token = auth_header.replace("Bearer ", "", 1).strip()
    if not token:
        token = request.query_params.get("token")

    stored = store.get_session_token_hash()
    if not stored:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Сессионный токен не инициализирован")

    if not token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Отсутствует токен")

    expected = _hash_token(token, stored["salt"])
    if not hmac.compare_digest(expected, stored["token_hash"]):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Неверный токен")


def bootstrap_token(token: str) -> dict:
    stored = store.get_session_token_hash()
    if stored:
        expected = _hash_token(token, stored["salt"])
        if not hmac.compare_digest(expected, stored["token_hash"]):
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Токен уже установлен")
        return {"status": "ок"}

    salt = _ensure_salt()
    token_hash = _hash_token(token, salt)
    store.set_session_token_hash(token_hash, salt)
    return {"status": "создано"}

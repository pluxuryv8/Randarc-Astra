from __future__ import annotations

import os
from typing import Optional

_runtime_passphrase: Optional[str] = None
_runtime_secrets: dict[str, str] = {}


def _vault_path() -> Optional[str]:
    return os.getenv("ASTRA_VAULT_PATH", ".astra/vault.bin")

def _local_secrets_path() -> Optional[str]:
    return os.getenv("ASTRA_LOCAL_SECRETS_PATH", "config/local.secrets.json")


def _vault_passphrase() -> Optional[str]:
    return _runtime_passphrase or os.getenv("ASTRA_VAULT_PASSPHRASE")


def set_runtime_passphrase(value: Optional[str]) -> None:
    global _runtime_passphrase
    _runtime_passphrase = value


def get_runtime_passphrase() -> Optional[str]:
    return _runtime_passphrase


def set_runtime_secret(key: str, value: str) -> None:
    _runtime_secrets[key] = value


def get_local_secret(key: str) -> Optional[str]:
    path = _local_secrets_path()
    if not path:
        return None
    try:
        if not os.path.exists(path):
            return None
        import json
        with open(path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        value = data.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
        return None
    except Exception:
        return None


def set_local_secret(key: str, value: str) -> None:
    path = _local_secrets_path()
    if not path:
        return
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    payload: dict[str, str] = {}
    try:
        if os.path.exists(path):
            import json
            with open(path, "r", encoding="utf-8") as handle:
                payload = json.load(handle) or {}
    except Exception:
        payload = {}
    payload[key] = value
    import json
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)


def get_secret(key: str) -> Optional[str]:
    if key in _runtime_secrets:
        return _runtime_secrets[key]
    # Переменные окружения имеют приоритет для временного использования
    if os.getenv(key):
        return os.getenv(key)
    local_value = get_local_secret(key)
    if local_value:
        return local_value

    path = _vault_path()
    passphrase = _vault_passphrase()
    if not path or not passphrase:
        return None

    try:
        from memory import vault
        return vault.get_secret(path=__import__("pathlib").Path(path), passphrase=passphrase, key=key)
    except ModuleNotFoundError:
        return None
    except Exception:
        return None

from __future__ import annotations

import os
from typing import Optional


def _vault_path() -> Optional[str]:
    return os.getenv("ASTRA_VAULT_PATH", ".astra/vault.bin")


def _vault_passphrase() -> Optional[str]:
    return os.getenv("ASTRA_VAULT_PASSPHRASE")


def get_secret(key: str) -> Optional[str]:
    # Переменные окружения имеют приоритет для временного использования
    if os.getenv(key):
        return os.getenv(key)

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

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from nacl import secret, pwhash, utils

MAGIC = b"ASVAULT1"
SALT_LEN = 16
NONCE_LEN = secret.SecretBox.NONCE_SIZE


class VaultError(Exception):
    pass


def _derive_key(passphrase: str, salt: bytes) -> bytes:
    return pwhash.argon2id.kdf(
        secret.SecretBox.KEY_SIZE,
        passphrase.encode("utf-8"),
        salt,
        opslimit=pwhash.argon2id.OPSLIMIT_MODERATE,
        memlimit=pwhash.argon2id.MEMLIMIT_MODERATE,
    )


def _encode(secrets: dict[str, Any], passphrase: str) -> bytes:
    salt = utils.random(SALT_LEN)
    key = _derive_key(passphrase, salt)
    box = secret.SecretBox(key)
    nonce = utils.random(NONCE_LEN)
    payload = json.dumps(secrets, ensure_ascii=False).encode("utf-8")
    ciphertext = box.encrypt(payload, nonce).ciphertext
    return MAGIC + salt + nonce + ciphertext


def _decode(raw: bytes, passphrase: str) -> dict[str, Any]:
    if not raw.startswith(MAGIC):
        raise VaultError("Неверный заголовок хранилища")
    offset = len(MAGIC)
    salt = raw[offset:offset + SALT_LEN]
    offset += SALT_LEN
    nonce = raw[offset:offset + NONCE_LEN]
    offset += NONCE_LEN
    ciphertext = raw[offset:]

    key = _derive_key(passphrase, salt)
    box = secret.SecretBox(key)
    try:
        plaintext = box.decrypt(nonce + ciphertext)
    except Exception as exc:
        raise VaultError("Неверная парольная фраза или повреждённое хранилище") from exc

    return json.loads(plaintext.decode("utf-8"))


def load_vault(path: Path, passphrase: str) -> dict[str, Any]:
    if not path.exists():
        return {}
    raw = path.read_bytes()
    return _decode(raw, passphrase)


def save_vault(path: Path, passphrase: str, secrets: dict[str, Any]) -> None:
    data = _encode(secrets, passphrase)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def set_secret(path: Path, passphrase: str, key: str, value: str) -> None:
    secrets = load_vault(path, passphrase)
    secrets[key] = value
    save_vault(path, passphrase, secrets)


def get_secret(path: Path, passphrase: str, key: str) -> str | None:
    secrets = load_vault(path, passphrase)
    return secrets.get(key)

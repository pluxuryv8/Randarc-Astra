from __future__ import annotations

import argparse
import os
from pathlib import Path

from memory.vault import set_secret


def main() -> None:
    parser = argparse.ArgumentParser(description="Управление зашифрованным хранилищем Randarc-Astra")
    parser.add_argument("key", help="Имя секрета")
    parser.add_argument("value", help="Значение секрета")
    parser.add_argument("--vault", default=os.environ.get("ASTRA_VAULT_PATH", ".astra/vault.bin"))
    parser.add_argument("--passphrase", default=os.environ.get("ASTRA_VAULT_PASSPHRASE"))
    args = parser.parse_args()

    if not args.passphrase:
        raise SystemExit("Требуется ASTRA_VAULT_PASSPHRASE")

    vault_path = Path(args.vault)
    set_secret(vault_path, args.passphrase, args.key, args.value)
    print(f"Секрет {args.key} сохранён в {vault_path}")


if __name__ == "__main__":
    main()

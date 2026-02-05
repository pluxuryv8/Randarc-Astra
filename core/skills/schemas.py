from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from jsonschema import validate
from jsonschema.exceptions import ValidationError


def load_schema(schema_path: str, base_dir: Path) -> dict[str, Any]:
    path = (base_dir / schema_path).resolve()
    if not path.exists():
        raise FileNotFoundError(f"Схема не найдена: {schema_path}")
    return json.loads(path.read_text(encoding="utf-8"))


def validate_inputs(schema: dict[str, Any], inputs: dict) -> None:
    validate(instance=inputs, schema=schema)

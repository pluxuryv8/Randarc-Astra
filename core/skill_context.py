from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass
class SkillContext:
    run: dict[str, Any]
    plan_step: dict[str, Any]
    task: dict[str, Any]
    settings: dict[str, Any]
    base_dir: str

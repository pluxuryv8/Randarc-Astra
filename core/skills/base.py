from __future__ import annotations

from typing import Optional, Protocol

from core.skills.result_types import SkillResult


class Skill(Protocol):
    name: str

    def build_approval(self, inputs: dict, ctx) -> Optional[dict]:
        return None

    def run(self, inputs: dict, ctx) -> SkillResult:
        raise NotImplementedError("Метод run не реализован")

    def execute(self, inputs: dict, ctx, approval: Optional[dict] = None) -> SkillResult:
        return self.run(inputs, ctx)

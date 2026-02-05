from __future__ import annotations

from core.bridge.desktop_bridge import DesktopBridge
from core.skills.result_types import SkillResult


def build_approval(inputs: dict, ctx) -> dict:
    actions = inputs.get("actions") or inputs.get("steps") or []
    return {
        "scope": "computer",
        "title": "Управление компьютером",
        "description": "Выполнение действий ОС (мышь/клавиатура/экран)",
        "proposed_actions": actions,
    }


def run(inputs: dict, ctx) -> SkillResult:
    actions = inputs.get("actions") or inputs.get("steps") or []
    bridge = DesktopBridge()
    result = bridge.computer_execute(actions)
    return SkillResult(
        what_i_did="Выполнены действия компьютера через десктоп-мост.",
        events=[{"message": result.get("summary", "действия компьютера выполнены"), "progress": {"current": 1, "total": 1, "unit": "действия"}}],
        confidence=0.6,
    )

from __future__ import annotations

from core.bridge.desktop_bridge import DesktopBridge
from core.skills.result_types import SkillResult


def build_approval(inputs: dict, ctx) -> dict:
    command = inputs.get("command") or ""
    return {
        "scope": "bash",
        "title": "Команда оболочки",
        "description": command,
        "proposed_actions": [{"command": command, "args": inputs.get("args") or []}],
    }


def run(inputs: dict, ctx) -> SkillResult:
    command = inputs.get("command") or ""
    bridge = DesktopBridge()
    _ = bridge.shell_execute(command)
    return SkillResult(
        what_i_did="Выполнена команда оболочки через десктоп-мост.",
        events=[{"message": "команда выполнена", "progress": {"current": 1, "total": 1, "unit": "команда"}}],
        confidence=0.6,
    )

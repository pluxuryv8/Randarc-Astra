from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from core.run_engine import RunEngine
from memory import store

ROOT = Path(__file__).resolve().parents[1]


class StubLLM:
    def chat(self, messages, model=None, temperature=0.2, json_schema=None, tools=None):
        payload = {
            "goal": "Тест автопилота",
            "plan": [],
            "step_summary": "ожидание",
            "reason": "",
            "actions": [{"type": "wait", "ms": 1}],
            "needs_user": False,
            "ask_confirm": {"required": False, "reason": "", "proposed_effect": ""},
            "done": True,
        }
        return {"choices": [{"message": {"content": json.dumps(payload, ensure_ascii=False)}}]}


class StubBridge:
    def autopilot_capture(self, max_width=1280, quality=60):
        return {
            "image_base64": "",
            "width": 1,
            "height": 1,
            "screen_width": 1,
            "screen_height": 1,
            "format": "jpeg",
        }

    def autopilot_act(self, action, image_width, image_height):
        return {"status": "ok"}


def _prepare_engine(tmp_path: Path):
    os.environ["ASTRA_DATA_DIR"] = str(tmp_path)
    store.reset_for_tests()
    store.init(tmp_path, ROOT / "memory" / "migrations")
    return RunEngine(ROOT)


def test_autopilot_events_persist(monkeypatch, tmp_path):
    engine = _prepare_engine(tmp_path)

    # stub LLM
    from core.providers import llm_client
    monkeypatch.setattr(llm_client, "build_llm_client", lambda settings: StubLLM())

    # stub bridge on the existing skill instance
    from skills.autopilot_computer.skill import skill as autopilot_skill
    autopilot_skill.bridge = StubBridge()

    project = store.create_project(
        "autopilot",
        [],
        {
            "llm": {"provider": "openai", "base_url": "https://api.openai.com/v1", "model": "gpt-4.1-mini"},
            "autopilot": {"max_cycles": 1, "max_actions": 1, "loop_delay_ms": 200},
        },
    )
    run = store.create_run(project["id"], "Покажи состояние", "execute_confirm")

    engine.create_plan(run["id"], run.get("query_text", ""))
    engine.start_run(run["id"])

    events = store.list_events(run["id"], limit=500)
    event_types = {e["type"] for e in events}

    assert "autopilot_state" in event_types
    assert "autopilot_action" in event_types

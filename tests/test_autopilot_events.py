from __future__ import annotations

import json
import os
from pathlib import Path

from core.executor.computer_executor import ExecutorConfig
from core.run_engine import RunEngine
from memory import store

ROOT = Path(__file__).resolve().parents[1]


class StubBrain:
    def call(self, request, ctx):
        from core.brain.types import LLMResponse
        payload = {
            "action_type": "done",
        }
        return LLMResponse(
            text=json.dumps(payload, ensure_ascii=False),
            usage=None,
            provider="local",
            model_id="stub",
            latency_ms=1,
            cache_hit=False,
            route_reason="stub",
        )


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

    # stub Brain + bridge for executor
    import core.brain
    monkeypatch.setattr(core.brain, "get_brain", lambda: StubBrain())
    engine.computer_executor.bridge = StubBridge()
    engine.computer_executor.brain = StubBrain()
    engine.computer_executor.config = ExecutorConfig(max_micro_steps=1, wait_timeout_ms=0, wait_poll_ms=0, wait_after_act_ms=0)

    project = store.create_project(
        "autopilot",
        [],
        {
            "llm": {"provider": "openai", "base_url": "http://localhost:1234/v1", "model": "gpt-4.1-mini"},
            "autopilot": {"max_cycles": 1, "max_actions": 1, "loop_delay_ms": 200},
        },
    )
    run = store.create_run(project["id"], "Покажи состояние", "execute_confirm")

    engine.create_plan(run)
    engine.start_run(run["id"])

    events = store.list_events(run["id"], limit=500)
    event_types = {e["type"] for e in events}

    assert "step_execution_started" in event_types
    assert "step_execution_finished" in event_types

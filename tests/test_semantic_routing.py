from __future__ import annotations

import os
import sys
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import core.intent_router as intent_router
from apps.api.main import create_app
from apps.api.routes import runs as runs_route
from core.brain.providers import ProviderError
from core.brain.types import LLMResponse
from core.semantic.decision import (
    SemanticDecision,
    SemanticDecisionError,
    SemanticMemoryItem,
    decide_semantic,
)
from memory import store


class FakeBrain:
    def __init__(self, text: str, *, status: str = "ok") -> None:
        self._text = text
        self._status = status

    def call(self, request, ctx=None):
        return LLMResponse(
            text=self._text,
            usage=None,
            provider="local",
            model_id="fake",
            latency_ms=1,
            cache_hit=False,
            route_reason="test",
            status=self._status,
            error_type=None,
        )


class FakeChatBrain:
    def call(self, request, ctx=None):
        return LLMResponse(
            text="Ок.",
            usage=None,
            provider="local",
            model_id="fake",
            latency_ms=1,
            cache_hit=False,
            route_reason="test",
            status="ok",
            error_type=None,
        )


class FailingChatBrain:
    def call(self, request, ctx=None):  # noqa: ANN001, ANN002
        raise ProviderError(
            "Local LLM request failed: timeout",
            provider="local",
            error_type="connection_error",
        )


def _init_store(tmp_path: Path):
    os.environ["ASTRA_DATA_DIR"] = str(tmp_path)
    os.environ["ASTRA_CHAT_FAST_PATH_ENABLED"] = "false"
    store.reset_for_tests()
    store.init(tmp_path, ROOT / "memory" / "migrations")


def _load_auth_token() -> str | None:
    data_dir = Path(os.environ.get("ASTRA_DATA_DIR", ROOT / ".astra"))
    token_path = data_dir / "auth.token"
    if not token_path.exists():
        return None
    token = token_path.read_text(encoding="utf-8").strip()
    return token or None


def _bootstrap(client: TestClient, token: str = "test-token") -> dict:
    file_token = _load_auth_token()
    token = file_token or token
    res = client.post("/api/v1/auth/bootstrap", json={"token": token})
    if res.status_code == 409 and file_token:
        token = file_token
    return {"Authorization": f"Bearer {token}"}


def _semantic(
    *,
    intent: str,
    memory_item: SemanticMemoryItem | None = None,
    plan_hint: list[str] | None = None,
) -> SemanticDecision:
    return SemanticDecision(
        intent=intent,
        confidence=0.92,
        memory_item=memory_item,
        plan_hint=plan_hint or [],
        response_style_hint=None,
        user_visible_note=None,
        raw={},
    )


def _memory_interpretation(
    *,
    should_store: bool,
    summary: str = "",
    facts: list[dict] | None = None,
    preferences: list[dict] | None = None,
):
    return {
        "should_store": should_store,
        "confidence": 0.9 if should_store else 0.2,
        "facts": facts or [],
        "preferences": preferences or [],
        "title": "Профиль пользователя",
        "summary": summary,
        "possible_facts": [],
    }


def test_semantic_decision_rejects_memory_array():
    brain = FakeBrain(
        '{"intent":"CHAT","confidence":0.9,"memory_item":[{"kind":"user_profile","text":"Имя пользователя: Михаил.","evidence":"меня Михаил зовут"}],"plan_hint":[],"response_style_hint":null,"user_visible_note":null}'
    )
    with pytest.raises(SemanticDecisionError, match="memory_item_must_be_object"):
        decide_semantic("кстати меня Михаил зовут", brain=brain)


def test_semantic_decision_parses_single_memory_item():
    brain = FakeBrain(
        '{"intent":"CHAT","confidence":0.9,"memory_item":{"kind":"user_profile","text":"Имя пользователя: Михаил.","evidence":"меня Михаил зовут"},"plan_hint":[],"response_style_hint":null,"user_visible_note":null}'
    )
    decision = decide_semantic("кстати меня Михаил зовут", brain=brain)
    assert decision.memory_item is not None
    assert decision.memory_item.text == "Имя пользователя: Михаил."


def test_chat_run_saves_memory_item(monkeypatch, tmp_path: Path):
    _init_store(tmp_path)
    monkeypatch.setattr(runs_route, "get_brain", lambda: FakeChatBrain())
    monkeypatch.setattr(
        runs_route,
        "interpret_user_message_for_memory",
        lambda *args, **kwargs: _memory_interpretation(
            should_store=True,
            summary="Пользователь представился как Михаил.",
            facts=[{"key": "user.name", "value": "Михаил", "confidence": 0.95, "evidence": "меня Михаил зовут"}],
        ),
    )
    monkeypatch.setattr(
        intent_router,
        "decide_semantic",
        lambda *args, **kwargs: _semantic(
            intent="CHAT",
            memory_item=SemanticMemoryItem(
                kind="user_profile",
                text="Имя пользователя: Михаил.",
                evidence="меня Михаил зовут",
            ),
        ),
    )

    client = TestClient(create_app())
    headers = _bootstrap(client)
    project = client.post("/api/v1/projects", json={"name": "semantic", "tags": [], "settings": {}}, headers=headers).json()

    response = client.post(
        f"/api/v1/projects/{project['id']}/runs",
        json={"query_text": "кстати меня Михаил зовут", "mode": "plan_only"},
        headers=headers,
    )
    assert response.status_code == 200
    assert response.json()["kind"] == "chat"

    memory_items: list[dict] = []
    for _ in range(40):
        memory_items = client.get("/api/v1/memory/list", headers=headers).json()
        if memory_items:
            break
        time.sleep(0.01)
    assert len(memory_items) == 1
    assert any(item.get("content") == "Пользователь представился как Михаил." for item in memory_items)
    assert any((item.get("meta") or {}).get("facts") for item in memory_items)


def test_chat_run_with_null_memory_item_does_not_write_memory(monkeypatch, tmp_path: Path):
    _init_store(tmp_path)
    monkeypatch.setattr(runs_route, "get_brain", lambda: FakeChatBrain())
    monkeypatch.setattr(
        runs_route,
        "interpret_user_message_for_memory",
        lambda *args, **kwargs: _memory_interpretation(should_store=False),
    )
    monkeypatch.setattr(intent_router, "decide_semantic", lambda *args, **kwargs: _semantic(intent="CHAT", memory_item=None))

    client = TestClient(create_app())
    headers = _bootstrap(client)
    project = client.post("/api/v1/projects", json={"name": "semantic", "tags": [], "settings": {}}, headers=headers).json()

    response = client.post(
        f"/api/v1/projects/{project['id']}/runs",
        json={"query_text": "привет", "mode": "plan_only"},
        headers=headers,
    )
    assert response.status_code == 200

    memory_items = client.get("/api/v1/memory/list", headers=headers).json()
    assert memory_items == []


def test_act_plan_hint_reaches_planner(monkeypatch, tmp_path: Path):
    _init_store(tmp_path)
    monkeypatch.setattr(
        runs_route,
        "interpret_user_message_for_memory",
        lambda *args, **kwargs: _memory_interpretation(should_store=False),
    )
    monkeypatch.setattr(
        intent_router,
        "decide_semantic",
        lambda *args, **kwargs: _semantic(intent="ACT", memory_item=None, plan_hint=["REMINDER_CREATE"]),
    )

    client = TestClient(create_app())
    headers = _bootstrap(client)
    project = client.post("/api/v1/projects", json={"name": "semantic", "tags": [], "settings": {}}, headers=headers).json()

    response = client.post(
        f"/api/v1/projects/{project['id']}/runs",
        json={"query_text": "через 1 час напомни выпить воды", "mode": "execute_confirm"},
        headers=headers,
    )
    assert response.status_code == 200

    payload = response.json()
    assert payload["kind"] == "act"
    kinds = {step.get("kind") for step in payload.get("plan", [])}
    assert "REMINDER_CREATE" in kinds


def test_act_reminder_without_trigger_word(monkeypatch, tmp_path: Path):
    _init_store(tmp_path)
    monkeypatch.setattr(
        runs_route,
        "interpret_user_message_for_memory",
        lambda *args, **kwargs: _memory_interpretation(should_store=False),
    )
    monkeypatch.setattr(
        intent_router,
        "decide_semantic",
        lambda *args, **kwargs: _semantic(intent="ACT", memory_item=None, plan_hint=["REMINDER_CREATE"]),
    )

    client = TestClient(create_app())
    headers = _bootstrap(client)
    project = client.post("/api/v1/projects", json={"name": "semantic", "tags": [], "settings": {}}, headers=headers).json()

    response = client.post(
        f"/api/v1/projects/{project['id']}/runs",
        json={"query_text": "через 1 час выпить воды", "mode": "execute_confirm"},
        headers=headers,
    )
    assert response.status_code == 200

    payload = response.json()
    assert payload["kind"] == "act"
    reminder_steps = [step for step in payload.get("plan", []) if step.get("kind") == "REMINDER_CREATE"]
    assert reminder_steps
    reminder_inputs = reminder_steps[0].get("inputs", {})
    assert reminder_inputs.get("text") == "выпить воды"
    assert isinstance(reminder_inputs.get("due_at"), str) and reminder_inputs.get("due_at")


def test_semantic_failure_degrades_to_chat_instead_of_502(monkeypatch, tmp_path: Path):
    _init_store(tmp_path)
    monkeypatch.setattr(runs_route, "get_brain", lambda: FakeChatBrain())
    monkeypatch.setattr(
        runs_route,
        "interpret_user_message_for_memory",
        lambda *args, **kwargs: _memory_interpretation(should_store=False),
    )

    def _boom(*args, **kwargs):  # noqa: ANN002, ANN003
        raise SemanticDecisionError("semantic_decision_llm_failed")

    monkeypatch.setattr(intent_router, "decide_semantic", _boom)

    client = TestClient(create_app())
    headers = _bootstrap(client)
    project = client.post("/api/v1/projects", json={"name": "semantic", "tags": [], "settings": {}}, headers=headers).json()

    response = client.post(
        f"/api/v1/projects/{project['id']}/runs",
        json={"query_text": "Сколько будет 2+2?", "mode": "plan_only"},
        headers=headers,
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["kind"] == "chat"
    assert payload["run"]["meta"]["intent"] == "CHAT"
    assert payload["run"]["meta"]["intent_path"] == "semantic_resilience"
    assert payload["run"]["meta"]["semantic_error_code"] == "semantic_decision_llm_failed"

    events = store.list_events(payload["run"]["id"], limit=50)
    event_types = [item.get("type") for item in events]
    assert "llm_request_failed" in event_types
    assert "run_failed" not in event_types


def test_chat_llm_timeout_degrades_to_fallback_chat(monkeypatch, tmp_path: Path):
    _init_store(tmp_path)
    monkeypatch.setattr(runs_route, "get_brain", lambda: FailingChatBrain())
    monkeypatch.setattr(
        runs_route,
        "interpret_user_message_for_memory",
        lambda *args, **kwargs: _memory_interpretation(should_store=False),
    )
    monkeypatch.setattr(
        intent_router,
        "decide_semantic",
        lambda *args, **kwargs: _semantic(intent="CHAT"),
    )

    client = TestClient(create_app())
    headers = _bootstrap(client)
    project = client.post("/api/v1/projects", json={"name": "semantic", "tags": [], "settings": {}}, headers=headers).json()

    response = client.post(
        f"/api/v1/projects/{project['id']}/runs",
        json={"query_text": "привет", "mode": "plan_only"},
        headers=headers,
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["kind"] == "chat"
    assert "Локальная модель сейчас недоступна" in payload["chat_response"]

    events = store.list_events(payload["run"]["id"], limit=50)
    event_types = [item.get("type") for item in events]
    assert "chat_response_generated" in event_types
    assert "run_failed" not in event_types


def test_fast_chat_path_skips_semantic_and_memory_interpreter(monkeypatch, tmp_path: Path):
    _init_store(tmp_path)
    monkeypatch.setenv("ASTRA_CHAT_FAST_PATH_ENABLED", "true")
    monkeypatch.setattr(runs_route, "get_brain", lambda: FakeChatBrain())

    def _semantic_should_not_run(*args, **kwargs):  # noqa: ANN002, ANN003
        raise AssertionError("semantic should be skipped by fast chat path")

    def _memory_should_not_run(*args, **kwargs):  # noqa: ANN002, ANN003
        raise AssertionError("memory interpreter should be skipped by fast chat path")

    monkeypatch.setattr(intent_router, "decide_semantic", _semantic_should_not_run)
    monkeypatch.setattr(runs_route, "interpret_user_message_for_memory", _memory_should_not_run)

    client = TestClient(create_app())
    headers = _bootstrap(client)
    project = client.post("/api/v1/projects", json={"name": "semantic", "tags": [], "settings": {}}, headers=headers).json()

    response = client.post(
        f"/api/v1/projects/{project['id']}/runs",
        json={"query_text": "214 + 43241", "mode": "plan_only"},
        headers=headers,
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["kind"] == "chat"
    assert payload["run"]["meta"]["intent_path"] == "fast_chat_path"
    assert payload["run"]["meta"]["memory_interpretation_error"] == "memory_interpreter_skipped_fast_path"


def test_memory_save_failure_is_non_blocking(monkeypatch, tmp_path: Path):
    _init_store(tmp_path)
    monkeypatch.setenv("ASTRA_CHAT_FAST_PATH_ENABLED", "false")
    monkeypatch.setattr(runs_route, "get_brain", lambda: FakeChatBrain())
    monkeypatch.setattr(
        runs_route,
        "interpret_user_message_for_memory",
        lambda *args, **kwargs: _memory_interpretation(
            should_store=True,
            summary="Пользователь представился как Михаил.",
            facts=[{"key": "user.name", "value": "Михаил", "confidence": 0.95, "evidence": "меня Михаил зовут"}],
        ),
    )
    monkeypatch.setattr(
        intent_router,
        "decide_semantic",
        lambda *args, **kwargs: _semantic(
            intent="CHAT",
            memory_item=SemanticMemoryItem(
                kind="user_profile",
                text="Имя пользователя: Михаил.",
                evidence="меня Михаил зовут",
            ),
        ),
    )

    def _memory_save_should_fail(*args, **kwargs):  # noqa: ANN002, ANN003
        raise RuntimeError("forced_memory_save_error")

    monkeypatch.setattr(runs_route.memory_save_skill, "run", _memory_save_should_fail)

    client = TestClient(create_app())
    headers = _bootstrap(client)
    project = client.post("/api/v1/projects", json={"name": "semantic", "tags": [], "settings": {}}, headers=headers).json()

    response = client.post(
        f"/api/v1/projects/{project['id']}/runs",
        json={"query_text": "кстати меня Михаил зовут", "mode": "plan_only"},
        headers=headers,
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["kind"] == "chat"

    events = []
    for _ in range(60):
        events = store.list_events(payload["run"]["id"], limit=80)
        if any(
            item.get("type") == "llm_request_failed"
            and (item.get("payload") or {}).get("error_type") == "memory_save_failed"
            for item in events
        ):
            break
        time.sleep(0.01)

    assert any(
        item.get("type") == "llm_request_failed"
        and (item.get("payload") or {}).get("error_type") == "memory_save_failed"
        for item in events
    )
    event_types = [item.get("type") for item in events]
    assert "run_failed" not in event_types

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
from core.skills.result_types import ArtifactCandidate, SkillResult, SourceCandidate
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


class FakeUncertainChatBrain:
    def call(self, request, ctx=None):
        return LLMResponse(
            text="Не знаю точно, возможно тут нужно проверить источники.",
            usage=None,
            provider="local",
            model_id="fake",
            latency_ms=1,
            cache_hit=False,
            route_reason="test",
            status="ok",
            error_type=None,
        )


class FakeLeakyChatBrain:
    def call(self, request, ctx=None):
        return LLMResponse(
            text=(
                "<think>Сначала сделаю внутренний разбор.</think>\n"
                "Internal reasoning:\n"
                "- check context\n"
                "Final answer: Кен Канеки - главный герой манги и аниме Tokyo Ghoul."
            ),
            usage=None,
            provider="local",
            model_id="fake",
            latency_ms=1,
            cache_hit=False,
            route_reason="test",
            status="ok",
            error_type=None,
        )


class CapturingChatBrain:
    def __init__(self, text: str = "Ок.") -> None:
        self._text = text
        self.last_request = None

    def call(self, request, ctx=None):
        self.last_request = request
        return LLMResponse(
            text=self._text,
            usage=None,
            provider="local",
            model_id="fake",
            latency_ms=1,
            cache_hit=False,
            route_reason="test",
            status="ok",
            error_type=None,
        )


class FakeVerboseChatBrain:
    def call(self, request, ctx=None):
        return LLMResponse(
            text=(
                "План на неделю: начни с умеренного дефицита калорий и ходьбы.\n\n"
                "План на неделю: начни с умеренного дефицита калорий и ходьбы.\n\n"
                "###!!!###\n"
                "День 1: кардио 30 минут.\n"
                "День 2: силовая тренировка на всё тело."
            ),
            usage=None,
            provider="local",
            model_id="fake",
            latency_ms=1,
            cache_hit=False,
            route_reason="test",
            status="ok",
            error_type=None,
        )


class FakeTemplateThenGoodChatBrain:
    def __init__(self) -> None:
        self.calls = 0

    def call(self, request, ctx=None):
        self.calls += 1
        if self.calls == 1:
            text = "Вот универсальный шаблон ответа. Это зависит от контекста, уточните детали."
        else:
            text = "Кен Канеки - главный герой манги и аниме Tokyo Ghoul."
        return LLMResponse(
            text=text,
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
    payload = response.json()
    assert payload["kind"] == "chat"

    memory_items: list[dict] = []
    for _ in range(40):
        memory_items = client.get("/api/v1/memory/list", headers=headers).json()
        if memory_items:
            break
        time.sleep(0.01)
    assert len(memory_items) == 1
    assert any(item.get("content") == "Пользователь представился как Михаил." for item in memory_items)
    assert any((item.get("meta") or {}).get("facts") for item in memory_items)

    run_snapshot = store.get_run(payload["run"]["id"])
    runtime_metrics = (run_snapshot or {}).get("meta", {}).get("runtime_metrics", {})
    assert runtime_metrics.get("intent") == "CHAT"
    assert runtime_metrics.get("fallback_path") == "none"
    assert runtime_metrics.get("chat_response_mode") == "direct_answer"
    assert runtime_metrics.get("chat_response_mode_reason") == "simple_query"
    assert isinstance(runtime_metrics.get("context_history_messages"), int)
    assert isinstance(runtime_metrics.get("context_history_chars"), int)
    assert isinstance(runtime_metrics.get("context_memory_items"), int)
    assert isinstance(runtime_metrics.get("context_memory_chars"), int)
    assert runtime_metrics.get("auto_web_research_triggered") is False
    assert isinstance(runtime_metrics.get("response_latency_ms"), int)
    style_meta = (run_snapshot or {}).get("meta", {}).get("selected_response_style_meta", {})
    assert style_meta.get("response_mode") == "direct_answer"
    assert isinstance(style_meta.get("sources"), list)
    assert "selected_style" in style_meta
    assert isinstance(runtime_metrics.get("selected_response_style_sources"), list)


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
    chat_events = [item for item in events if item.get("type") == "chat_response_generated"]
    assert chat_events
    emitted_payload = chat_events[-1].get("payload") or {}
    assert emitted_payload.get("reason_code") == "semantic_resilience_fallback"


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
    assert "Текущий запрос: привет." in payload["chat_response"]

    events = store.list_events(payload["run"]["id"], limit=50)
    event_types = [item.get("type") for item in events]
    assert "chat_response_generated" in event_types
    assert "run_failed" not in event_types
    chat_events = [item for item in events if item.get("type") == "chat_response_generated"]
    assert chat_events
    runtime_metrics = (chat_events[-1].get("payload") or {}).get("runtime_metrics") or {}
    assert runtime_metrics.get("intent") == "CHAT"
    assert runtime_metrics.get("fallback_path") in {"chat_llm_fallback", "chat_llm_fallback_web_research"}
    assert isinstance(runtime_metrics.get("response_latency_ms"), int)
    emitted_payload = chat_events[-1].get("payload") or {}
    assert emitted_payload.get("reason_code") in {"chat_llm_fallback", "chat_llm_fallback_web_research"}


def test_chat_uncertain_response_uses_auto_web_research(monkeypatch, tmp_path: Path):
    _init_store(tmp_path)
    monkeypatch.setenv("ASTRA_CHAT_AUTO_WEB_RESEARCH_ENABLED", "true")
    monkeypatch.setattr(runs_route, "get_brain", lambda: FakeUncertainChatBrain())
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

    answer_path = tmp_path / "web_research_answer.md"
    answer_path.write_text("Кен Канеки - главный герой манги и аниме Tokyo Ghoul.", encoding="utf-8")

    def _fake_web_research(_inputs, _ctx):  # noqa: ANN001
        return SkillResult(
            what_i_did="Проведён web research: прочитано 1 страниц, раундов 1",
            sources=[SourceCandidate(url="https://example.org/tokyo-ghoul", title="Tokyo Ghoul Wiki")],
            artifacts=[
                ArtifactCandidate(
                    type="web_research_answer_md",
                    title="Web Research Answer",
                    content_uri=str(answer_path),
                    meta={},
                )
            ],
            events=[
                {
                    "type": "task_progress",
                    "message": "Раунд 1/1: поиск источников",
                    "reason_code": "search_round_started",
                    "query": "Кто такой Кен Канеки?",
                    "progress": {"current": 1, "total": 1, "unit": "round"},
                }
            ],
            confidence=0.9,
        )

    monkeypatch.setattr(runs_route.web_research_skill, "run", _fake_web_research)

    client = TestClient(create_app())
    headers = _bootstrap(client)
    project = client.post("/api/v1/projects", json={"name": "semantic", "tags": [], "settings": {}}, headers=headers).json()

    response = client.post(
        f"/api/v1/projects/{project['id']}/runs",
        json={"query_text": "Кто такой Кен Канеки?", "mode": "plan_only"},
        headers=headers,
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["kind"] == "chat"
    assert "Кен Канеки" in payload["chat_response"]
    assert "https://example.org/tokyo-ghoul" in payload["chat_response"]

    events = store.list_events(payload["run"]["id"], limit=80)
    chat_events = [item for item in events if item.get("type") == "chat_response_generated"]
    assert chat_events
    last_payload = chat_events[-1].get("payload") or {}
    assert last_payload.get("provider") == "web_research"
    runtime_metrics = last_payload.get("runtime_metrics") or {}
    assert runtime_metrics.get("auto_web_research_triggered") is True
    assert runtime_metrics.get("auto_web_research_reason") in {"uncertain_response", "off_topic", "ru_language_mismatch"}
    assert runtime_metrics.get("fallback_path") == "chat_web_research"
    assert isinstance(runtime_metrics.get("response_latency_ms"), int)
    run_snapshot = store.get_run(payload["run"]["id"])
    persisted_metrics = (run_snapshot or {}).get("meta", {}).get("runtime_metrics", {})
    assert persisted_metrics.get("fallback_path") == "chat_web_research"
    assert persisted_metrics.get("auto_web_research_triggered") is True
    assert any(
        item.get("type") == "task_progress"
        and (item.get("payload") or {}).get("reason_code") == "search_round_started"
        and (item.get("payload") or {}).get("query") == "Кто такой Кен Канеки?"
        for item in events
    )


def test_internal_reasoning_notes_are_not_exposed_in_chat_ui(monkeypatch, tmp_path: Path):
    _init_store(tmp_path)
    monkeypatch.setattr(runs_route, "get_brain", lambda: FakeLeakyChatBrain())
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
        json={"query_text": "Кто такой Кен Канеки?", "mode": "plan_only"},
        headers=headers,
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["kind"] == "chat"
    assert "Кен Канеки" in payload["chat_response"]
    assert "<think>" not in payload["chat_response"]
    assert "Internal reasoning" not in payload["chat_response"]
    assert "Final answer" not in payload["chat_response"]

    events = store.list_events(payload["run"]["id"], limit=60)
    chat_events = [item for item in events if item.get("type") == "chat_response_generated"]
    assert chat_events
    emitted_text = str((chat_events[-1].get("payload") or {}).get("text") or "")
    assert "<think>" not in emitted_text
    assert "Internal reasoning" not in emitted_text


def test_chat_final_postprocessor_adds_summary_and_removes_duplicates(monkeypatch, tmp_path: Path):
    _init_store(tmp_path)
    monkeypatch.setattr(runs_route, "get_brain", lambda: FakeVerboseChatBrain())
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
        json={"query_text": "сделай план тренировок на неделю", "mode": "plan_only"},
        headers=headers,
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["kind"] == "chat"
    assert payload["chat_response"].startswith("Краткий итог:")
    assert "\n\nДетали:\n" in payload["chat_response"]
    assert payload["chat_response"].count("План на неделю: начни с умеренного дефицита калорий и ходьбы.") == 1
    assert "###!!!###" not in payload["chat_response"]

    events = store.list_events(payload["run"]["id"], limit=60)
    chat_events = [item for item in events if item.get("type") == "chat_response_generated"]
    assert chat_events
    emitted_text = str((chat_events[-1].get("payload") or {}).get("text") or "")
    assert emitted_text.startswith("Краткий итог:")
    assert "\n\nДетали:\n" in emitted_text
    assert "###!!!###" not in emitted_text


def test_template_like_chat_answer_is_regenerated_once(monkeypatch, tmp_path: Path):
    _init_store(tmp_path)
    brain = FakeTemplateThenGoodChatBrain()
    monkeypatch.setattr(runs_route, "get_brain", lambda: brain)
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
        json={"query_text": "Кто такой Кен Канеки?", "mode": "plan_only"},
        headers=headers,
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["kind"] == "chat"
    assert "Кен Канеки" in payload["chat_response"]
    assert "универсальный шаблон" not in payload["chat_response"].lower()
    assert brain.calls == 2

    events = store.list_events(payload["run"]["id"], limit=60)
    chat_events = [item for item in events if item.get("type") == "chat_response_generated"]
    assert chat_events
    emitted_text = str((chat_events[-1].get("payload") or {}).get("text") or "")
    assert "универсальный шаблон" not in emitted_text.lower()


def test_complex_chat_query_switches_to_step_by_step_response_mode(monkeypatch, tmp_path: Path):
    _init_store(tmp_path)
    brain = CapturingChatBrain("Сначала делай разминку. Потом основная тренировка.")
    monkeypatch.setattr(runs_route, "get_brain", lambda: brain)
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

    query = "Составь подробный план тренировок на месяц с этапами, рисками и метриками прогресса"
    response = client.post(
        f"/api/v1/projects/{project['id']}/runs",
        json={"query_text": query, "mode": "plan_only"},
        headers=headers,
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["kind"] == "chat"
    assert payload["run"]["meta"]["chat_response_mode"] == "step_by_step_plan"
    assert "complex_keyword" in str(payload["run"]["meta"]["chat_response_mode_reason"] or "")

    assert brain.last_request is not None
    system_prompt = str((brain.last_request.messages or [{}])[0].get("content") or "")
    assert "Формат ответа: step-by-step plan." in system_prompt
    assert brain.last_request.max_tokens > runs_route._chat_num_predict_default()
    assert brain.last_request.temperature < runs_route._chat_temperature_default()
    assert (brain.last_request.metadata or {}).get("chat_inference_profile") == "complex"

    run_snapshot = store.get_run(payload["run"]["id"])
    runtime_metrics = (run_snapshot or {}).get("meta", {}).get("runtime_metrics", {})
    assert runtime_metrics.get("chat_response_mode") == "step_by_step_plan"
    assert runtime_metrics.get("chat_inference_profile") == "complex"
    style_meta = (run_snapshot or {}).get("meta", {}).get("selected_response_style_meta", {})
    assert style_meta.get("response_mode") == "step_by_step_plan"
    assert style_meta.get("detail_requested") is True

    events = store.list_events(payload["run"]["id"], limit=60)
    chat_events = [item for item in events if item.get("type") == "chat_response_generated"]
    assert chat_events
    emitted_payload = chat_events[-1].get("payload") or {}
    assert emitted_payload.get("response_mode") == "step_by_step_plan"


def test_simple_chat_query_uses_fast_inference_profile(monkeypatch, tmp_path: Path):
    _init_store(tmp_path)
    brain = CapturingChatBrain("4")
    monkeypatch.setattr(runs_route, "get_brain", lambda: brain)
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
        json={"query_text": "2+2?", "mode": "plan_only"},
        headers=headers,
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["kind"] == "chat"

    assert brain.last_request is not None
    assert brain.last_request.max_tokens < runs_route._chat_num_predict_default()
    assert brain.last_request.temperature < runs_route._chat_temperature_default()
    assert (brain.last_request.metadata or {}).get("chat_inference_profile") == "fast"

    run_snapshot = store.get_run(payload["run"]["id"])
    runtime_metrics = (run_snapshot or {}).get("meta", {}).get("runtime_metrics", {})
    assert runtime_metrics.get("chat_response_mode") == "direct_answer"
    assert runtime_metrics.get("chat_inference_profile") == "fast"


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


def test_fast_chat_boundary_simple_vs_complex(monkeypatch):
    monkeypatch.setenv("ASTRA_CHAT_FAST_PATH_ENABLED", "true")
    assert runs_route._is_fast_chat_candidate("214 + 43241", qa_mode=False) is True
    assert (
        runs_route._is_fast_chat_candidate(
            "Составь подробный план тренировок на месяц с этапами, рисками и метриками прогресса",
            qa_mode=False,
        )
        is False
    )


def test_complex_chat_request_skips_fast_path_and_uses_semantic(monkeypatch, tmp_path: Path):
    _init_store(tmp_path)
    monkeypatch.setenv("ASTRA_CHAT_FAST_PATH_ENABLED", "true")
    monkeypatch.setattr(runs_route, "get_brain", lambda: FakeChatBrain())
    monkeypatch.setattr(
        runs_route,
        "interpret_user_message_for_memory",
        lambda *args, **kwargs: _memory_interpretation(should_store=False),
    )
    called = {"semantic": 0}

    def _semantic_called(*args, **kwargs):  # noqa: ANN002, ANN003
        called["semantic"] += 1
        return _semantic(intent="CHAT")

    monkeypatch.setattr(intent_router, "decide_semantic", _semantic_called)

    client = TestClient(create_app())
    headers = _bootstrap(client)
    project = client.post("/api/v1/projects", json={"name": "semantic", "tags": [], "settings": {}}, headers=headers).json()

    response = client.post(
        f"/api/v1/projects/{project['id']}/runs",
        json={
            "query_text": "Составь подробный план тренировок на месяц с этапами, рисками и метриками прогресса",
            "mode": "plan_only",
        },
        headers=headers,
    )
    assert response.status_code == 200
    payload = response.json()
    assert payload["kind"] == "chat"
    assert payload["run"]["meta"]["intent_path"] == "semantic"
    assert payload["run"]["meta"]["memory_interpretation_error"] is None
    assert called["semantic"] == 1


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

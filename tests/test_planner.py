from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core import planner
from core.intent_router import INTENT_ACT, INTENT_CHAT


def _run(query: str, intent: str, meta: dict | None = None):
    payload = {"query_text": query, "meta": {"intent": intent}}
    if meta:
        payload["meta"].update(meta)
    return payload


def test_planner_chat_response():
    run = _run("мне грустно", INTENT_CHAT)
    plan = planner.create_plan_for_run(run)
    assert len(plan) == 1
    assert plan[0]["kind"] == "CHAT_RESPONSE"


def test_planner_default_act_without_hints():
    run = _run("Сделай задачу", INTENT_ACT)
    plan = planner.create_plan_for_run(run)
    assert plan
    assert plan[0]["kind"] == "COMPUTER_ACTIONS"


def test_planner_memory_commit_from_plan_hint():
    run = _run(
        "кстати меня Михаил зовут",
        INTENT_ACT,
        {
            "plan_hint": ["MEMORY_COMMIT"],
            "memory_item": {
                "kind": "user_profile",
                "text": "Имя пользователя: Михаил.",
                "evidence": "меня Михаил зовут",
            },
        },
    )
    plan = planner.create_plan_for_run(run)
    assert plan[0]["kind"] == "MEMORY_COMMIT"
    assert plan[0]["inputs"]["facts"] == ["Имя пользователя: Михаил."]


def test_planner_adds_memory_commit_from_memory_interpretation():
    run = _run(
        "меня зовут Михаил, отвечай коротко",
        INTENT_ACT,
        {
            "plan_hint": ["COMPUTER_ACTIONS"],
            "memory_interpretation": {
                "should_store": True,
                "confidence": 0.91,
                "title": "Профиль пользователя",
                "summary": "Пользователь представился как Михаил и попросил короткие ответы.",
                "facts": [
                    {"key": "user.name", "value": "Михаил", "confidence": 0.95, "evidence": "меня зовут Михаил"}
                ],
                "preferences": [
                    {"key": "style.brevity", "value": "short", "confidence": 0.82, "evidence": "отвечай коротко"}
                ],
            },
        },
    )
    plan = planner.create_plan_for_run(run)
    kinds = [step["kind"] for step in plan]
    assert "MEMORY_COMMIT" in kinds
    memory_step = next(step for step in plan if step["kind"] == "MEMORY_COMMIT")
    payload = memory_step["inputs"]["memory_payload"]
    assert payload["summary"] == "Пользователь представился как Михаил и попросил короткие ответы."
    assert payload["facts"][0]["key"] == "user.name"


def test_planner_memory_commit_without_memory_item_fails():
    run = _run(
        "запомни это",
        INTENT_ACT,
        {
            "plan_hint": ["MEMORY_COMMIT"],
        },
    )
    with pytest.raises(RuntimeError, match="planner_memory_item_missing"):
        planner.create_plan_for_run(run)


def test_planner_reminder_from_plan_hint():
    run = _run(
        "через 1 час напомни выпить воды",
        INTENT_ACT,
        {"plan_hint": ["REMINDER_CREATE"]},
    )
    plan = planner.create_plan_for_run(run)
    assert plan[0]["kind"] == "REMINDER_CREATE"
    assert "due_at" in plan[0]["inputs"]


def test_planner_web_research_from_plan_hint():
    run = _run(
        "Найди источники по экономике",
        INTENT_ACT,
        {"plan_hint": ["WEB_RESEARCH"]},
    )
    plan = planner.create_plan_for_run(run)
    assert plan
    assert plan[0]["kind"] == "WEB_RESEARCH"
    assert plan[0]["skill_name"] == "web_research"
    assert plan[0]["inputs"]["mode"] == "deep"


def test_planner_clarify_step_inserted():
    run = _run(
        "сделай это",
        INTENT_ACT,
        {"needs_clarification": True, "intent_questions": ["Что именно нужно сделать?"]},
    )
    plan = planner.create_plan_for_run(run)
    assert plan
    assert plan[0]["kind"] == "CLARIFY_QUESTION"
    assert plan[0]["inputs"]["questions"] == ["Что именно нужно сделать?"]


def test_planner_main_path_does_not_call_legacy_text_detectors(monkeypatch):
    def _boom(*args, **kwargs):
        raise AssertionError("legacy_detectors_called")

    monkeypatch.setattr(planner, "_build_steps_from_text", _boom)

    run = _run("Сделай задачу", INTENT_ACT, {"plan_hint": ["COMPUTER_ACTIONS"]})
    plan = planner.create_plan_for_run(run)
    assert plan
    assert plan[0]["kind"] == "COMPUTER_ACTIONS"


def test_planner_legacy_detectors_disabled_by_default_without_plan_hint(monkeypatch):
    def _boom(*args, **kwargs):
        raise AssertionError("legacy_detectors_called")

    monkeypatch.delenv("ASTRA_LEGACY_DETECTORS", raising=False)
    monkeypatch.setattr(planner, "_build_steps_from_text", _boom)

    run = _run("запомни это", INTENT_ACT)
    plan = planner.create_plan_for_run(run)
    assert plan
    assert plan[0]["kind"] == "COMPUTER_ACTIONS"

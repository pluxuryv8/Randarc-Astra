from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core import planner
from core.intent_router import INTENT_ACT, INTENT_CHAT


def _run(query: str, intent: str):
    return {"query_text": query, "meta": {"intent": intent}}


def test_planner_playlist_plan():
    run = _run("Создай плейлист в Яндекс Музыке", INTENT_ACT)
    plan = planner.create_plan_for_run(run)
    kinds = {step["kind"] for step in plan}
    assert "BROWSER_RESEARCH_UI" in kinds
    assert any(step["success_criteria"] for step in plan)


def test_planner_sort_desktop():
    run = _run("Отсортируй иконки на рабочем столе", INTENT_ACT)
    plan = planner.create_plan_for_run(run)
    kinds = {step["kind"] for step in plan}
    assert "FILE_ORGANIZE" in kinds


def test_planner_vscode_errors():
    run = _run("Посмотри проект в VSCode и найди ошибки", INTENT_ACT)
    plan = planner.create_plan_for_run(run)
    kinds = {step["kind"] for step in plan}
    assert "CODE_ASSIST" in kinds


def test_planner_document_write():
    run = _run("Напиши доклад на 2 листа", INTENT_ACT)
    plan = planner.create_plan_for_run(run)
    kinds = {step["kind"] for step in plan}
    assert "DOCUMENT_WRITE" in kinds


def test_planner_chat_response():
    run = _run("мне грустно поговори со мной", INTENT_CHAT)
    plan = planner.create_plan_for_run(run)
    assert len(plan) == 1
    assert plan[0]["kind"] == "CHAT_RESPONSE"


def test_planner_memory_commit():
    run = _run("Запомни, что я люблю кофе", INTENT_ACT)
    plan = planner.create_plan_for_run(run)
    kinds = {step["kind"] for step in plan}
    assert "MEMORY_COMMIT" in kinds


def test_planner_reminder_create():
    run = _run("в 16:00 напомни купить хлеб", INTENT_ACT)
    plan = planner.create_plan_for_run(run)
    kinds = {step["kind"] for step in plan}
    assert "REMINDER_CREATE" in kinds

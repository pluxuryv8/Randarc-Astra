from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from apps.api.routes import runs as runs_route
from core.chat_context import build_memory_dump_response
from core.skill_context import SkillContext
from memory import store
from skills.memory_save import skill as memory_skill


def _init_store(tmp_path: Path):
    os.environ["ASTRA_DATA_DIR"] = str(tmp_path)
    store.reset_for_tests()
    store.init(tmp_path, ROOT / "memory" / "migrations")


def test_memory_save_name(tmp_path: Path):
    _init_store(tmp_path)
    project = store.create_project("Mem", [], {})
    run = store.create_run(project["id"], "кстати, меня Михаил зовут", "execute_confirm")

    step = {
        "id": "step-memory",
        "run_id": run["id"],
        "step_index": 0,
        "title": "Сохранить в память",
        "skill_name": "memory_save",
        "inputs": {"content": run["query_text"], "facts": ["Имя пользователя: Михаил."]},
        "depends_on": [],
        "status": "created",
        "kind": "MEMORY_COMMIT",
        "success_criteria": "ok",
        "danger_flags": [],
        "requires_approval": False,
        "artifacts_expected": [],
    }
    store.insert_plan_steps(run["id"], [step])
    task = store.create_task(run["id"], step["id"], attempt=1)

    ctx = SkillContext(run=run, plan_step=step, task=task, settings={}, base_dir=str(ROOT))
    memory_skill.run(step["inputs"], ctx)

    items = store.list_user_memories()
    assert any("Михаил" in item.get("content", "") for item in items)


def test_memory_dump_uses_profile_items(tmp_path: Path):
    _init_store(tmp_path)
    store.create_user_memory(None, "Имя пользователя: Михаил.", [])
    store.create_user_memory(None, "Предпочтение пользователя: короткие ответы.", [])

    items = store.list_user_memories()
    response = build_memory_dump_response(items)

    assert "Вот что я помню о тебе" in response
    assert "Михаил" in response
    assert "короткие ответы" in response


def test_memory_dump_empty():
    response = build_memory_dump_response([])
    assert "Пока ничего не помню" in response


def test_chat_system_prompt_uses_name_and_style_from_profile(tmp_path: Path):
    _init_store(tmp_path)
    store.create_user_memory(
        "Профиль пользователя",
        "Пользователь представился как Михаил.",
        [],
        meta={
            "summary": "Пользователь представился как Михаил.",
            "facts": [{"key": "user.name", "value": "Михаил", "confidence": 0.95, "evidence": "меня зовут Михаил"}],
            "preferences": [{"key": "style.brevity", "value": "short", "confidence": 0.86}],
        },
    )
    memories = store.list_user_memories()
    prompt = runs_route._build_chat_system_prompt(memories, None)
    assert "Имя пользователя: Михаил" in prompt
    assert "Отвечай коротко и по делу." in prompt

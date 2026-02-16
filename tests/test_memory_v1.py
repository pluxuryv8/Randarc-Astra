from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from fastapi.testclient import TestClient

from apps.api.main import create_app
from core import planner
from core.skill_context import SkillContext
from memory import store
from skills.memory_save import skill as memory_skill


def _init_store(tmp_path: Path):
    os.environ["ASTRA_DATA_DIR"] = str(tmp_path)
    store.reset_for_tests()
    store.init(tmp_path, ROOT / "memory" / "migrations")


def _make_client():
    temp_dir = Path(tempfile.mkdtemp())
    _init_store(temp_dir)
    return TestClient(create_app())


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


def test_user_memory_store_crud(tmp_path: Path):
    _init_store(tmp_path)
    memory = store.create_user_memory("Title", "Content", ["tag"], source="user_command")
    items = store.list_user_memories()
    assert len(items) == 1
    assert items[0]["id"] == memory["id"]

    pinned = store.set_user_memory_pinned(memory["id"], True)
    assert pinned and pinned["pinned"] is True

    deleted = store.delete_user_memory(memory["id"])
    assert deleted and deleted["is_deleted"] is True
    assert store.list_user_memories() == []


def test_user_memory_limit(tmp_path: Path, monkeypatch):
    _init_store(tmp_path)
    monkeypatch.setenv("ASTRA_MEMORY_MAX_CHARS", "10")
    try:
        store.create_user_memory("Title", "X" * 11, [], source="user_command")
        assert False, "expected ValueError"
    except ValueError as exc:
        assert "content_too_long" in str(exc)


def test_memory_api_create_list_delete(monkeypatch):
    from apps.api.routes import memory as memory_routes

    monkeypatch.setattr(memory_routes, "normalize_memory_texts", lambda content, **kwargs: ["Факт: Hello memory."])

    client = _make_client()
    headers = _bootstrap(client)

    created = client.post("/api/v1/memory/create", json={"content": "Hello memory"}, headers=headers)
    assert created.status_code == 200
    memory_id = created.json().get("id")
    assert memory_id

    listed = client.get("/api/v1/memory/list?query=Hello", headers=headers)
    assert listed.status_code == 200
    assert any(item.get("id") == memory_id for item in listed.json())

    deleted = client.delete(f"/api/v1/memory/{memory_id}", headers=headers)
    assert deleted.status_code == 200


def test_memory_commit_step_only_from_plan_hint():
    run_no = {"query_text": "сделай отчёт", "meta": {"intent": "ACT"}}
    steps_no = planner.create_plan_for_run(run_no)
    assert not any(step.get("kind") == "MEMORY_COMMIT" for step in steps_no)

    run_yes = {
        "query_text": "что-нибудь",
        "meta": {
            "intent": "ACT",
            "plan_hint": ["MEMORY_COMMIT"],
            "memory_item": {
                "kind": "user_preference",
                "text": "Предпочтение пользователя: короткие ответы.",
                "evidence": "отвечай коротко",
            },
        },
    }
    steps_yes = planner.create_plan_for_run(run_yes)
    assert any(step.get("kind") == "MEMORY_COMMIT" for step in steps_yes)


def test_memory_save_skill_creates_entry(tmp_path: Path):
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
    assert len(items) == 1
    events = store.list_events(run["id"], limit=50)
    assert any(e.get("type") == "memory_saved" for e in events)


def test_memory_save_one_item_per_message(tmp_path: Path, monkeypatch):
    _init_store(tmp_path)
    project = store.create_project("Mem", [], {})
    raw_text = "отвечай коротко и называй меня Михаил"
    run = store.create_run(project["id"], raw_text, "execute_confirm")

    step = {
        "id": "step-memory",
        "run_id": run["id"],
        "step_index": 0,
        "title": "Сохранить в память",
        "skill_name": "memory_save",
        "inputs": {"content": raw_text},
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

    monkeypatch.setattr(
        memory_skill,
        "normalize_memory_texts",
        lambda content, **kwargs: [
            "Имя пользователя: Михаил.",
            "Предпочтение пользователя: короткие ответы.",
        ],
    )

    memory_skill.run(step["inputs"], ctx)

    items = store.list_user_memories()
    assert len(items) == 1
    assert items[0]["content"] == "Имя пользователя: Михаил."
    assert items[0]["content"] != raw_text

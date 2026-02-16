from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.chat_context import build_chat_messages
from memory import store


def _init_db(tmp_path: Path) -> None:
    store.reset_for_tests()
    store.init(tmp_path, ROOT / "memory" / "migrations")


def _create_chat_run(project_id: str, text: str, parent_run_id: str | None = None) -> dict:
    run = store.create_run(
        project_id,
        text,
        "plan_only",
        parent_run_id=parent_run_id,
        purpose="chat_only",
        meta={"intent": "CHAT"},
    )
    store.add_event(
        run["id"],
        "chat_response_generated",
        "info",
        "Ответ сформирован",
        payload={"text": f"Ответ на: {text}"},
    )
    return run


def test_list_recent_chat_turns_order(tmp_path: Path):
    _init_db(tmp_path)
    project = store.create_project("chat", [], {})
    run1 = _create_chat_run(project["id"], "Привет")
    run2 = _create_chat_run(project["id"], "Как дела?", parent_run_id=run1["id"])
    run3 = _create_chat_run(project["id"], "Расскажи анекдот", parent_run_id=run2["id"])

    history = store.list_recent_chat_turns(run3["id"], limit_turns=2)
    contents = [item["content"] for item in history]
    roles = [item["role"] for item in history]

    assert contents == [
        "Как дела?",
        "Ответ на: Как дела?",
        "Расскажи анекдот",
        "Ответ на: Расскажи анекдот",
    ]
    assert roles == ["user", "assistant", "user", "assistant"]


def test_build_chat_messages_injection():
    system_text = "system"
    history = [
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "hello"},
    ]
    messages = build_chat_messages(system_text, history, "next")
    assert messages == [
        {"role": "system", "content": "system"},
        {"role": "user", "content": "hi"},
        {"role": "assistant", "content": "hello"},
        {"role": "user", "content": "next"},
    ]

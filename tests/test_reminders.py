from __future__ import annotations

import os
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi.testclient import TestClient

from apps.api.main import create_app
from core.reminders.parser import parse_reminder_text
from core.reminders.scheduler import ReminderScheduler
from memory import store

ROOT = Path(__file__).resolve().parents[1]


def _init_store(tmp_path: Path):
    os.environ["ASTRA_DATA_DIR"] = str(tmp_path)
    store.reset_for_tests()
    store.init(tmp_path, ROOT / "memory" / "migrations")


def _make_client():
    temp_dir = Path(tempfile.mkdtemp())
    _init_store(temp_dir)
    return TestClient(create_app())


def _bootstrap(client: TestClient, token: str = "test-token") -> dict:
    client.post("/api/v1/auth/bootstrap", json={"token": token})
    return {"Authorization": f"Bearer {token}"}


def test_parse_reminder_phrases():
    now = datetime(2025, 1, 1, 12, 0, tzinfo=timezone.utc)
    due_at, text, question = parse_reminder_text("через 2 часа напомни сделать чай", now=now)
    assert question is None
    assert text == "сделать чай"
    assert due_at is not None

    due_at, text, question = parse_reminder_text("завтра в 10:30 напомни про встречу", now=now)
    assert question is None
    assert "встречу" in text
    assert due_at is not None

    due_at, text, question = parse_reminder_text("напомни купить молоко", now=now)
    assert due_at is None
    assert question is not None


def test_reminder_store_and_scheduler_local(tmp_path: Path, monkeypatch):
    _init_store(tmp_path)
    project = store.create_project("Reminders", [], {})
    run = store.create_run(project["id"], "через 1 минуту напомни тест", "execute_confirm")

    due_at = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat().replace("+00:00", "Z")
    reminder = store.create_reminder(due_at, "тест", delivery="local", run_id=run["id"], source="user_command")

    scheduler = ReminderScheduler(poll_interval=1)
    scheduler.run_once()
    scheduler.run_once()

    updated = store.get_reminder(reminder["id"])
    assert updated is not None
    assert updated["status"] == "sent"

    events = store.list_events(run["id"], limit=50)
    assert any(evt.get("type") == "reminder_sent" for evt in events)


def test_reminder_scheduler_telegram_not_configured(tmp_path: Path, monkeypatch):
    _init_store(tmp_path)
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)

    project = store.create_project("Reminders", [], {})
    run = store.create_run(project["id"], "через 1 минуту напомни тест", "execute_confirm")

    due_at = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat().replace("+00:00", "Z")
    reminder = store.create_reminder(due_at, "тест", delivery="telegram", run_id=run["id"], source="user_command")

    scheduler = ReminderScheduler(poll_interval=1)
    scheduler.run_once()

    updated = store.get_reminder(reminder["id"])
    assert updated is not None
    assert updated["status"] == "failed"
    assert updated["last_error"] == "telegram_not_configured"


def test_reminders_api_create_list_cancel():
    client = _make_client()
    headers = _bootstrap(client)

    due_at = (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat().replace("+00:00", "Z")
    created = client.post("/api/v1/reminders/create", json={"due_at": due_at, "text": "test"}, headers=headers)
    assert created.status_code == 200
    reminder_id = created.json().get("id")
    assert reminder_id

    listed = client.get("/api/v1/reminders", headers=headers)
    assert listed.status_code == 200
    assert any(item.get("id") == reminder_id for item in listed.json())

    cancelled = client.delete(f"/api/v1/reminders/{reminder_id}", headers=headers)
    assert cancelled.status_code == 200
    assert cancelled.json().get("status") == "cancelled"

from __future__ import annotations

import json
import os
import sqlite3
import threading
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from .db import ensure_db, now_iso

_lock = threading.Lock()
_conn: Optional[sqlite3.Connection] = None

# EN kept: статусы и ключи в БД — контракт между API и UI


def init(base_dir: Path, migrations_dir: Path) -> None:
    global _conn
    with _lock:
        if _conn is None:
            _conn = ensure_db(base_dir, migrations_dir)


def reset_for_tests() -> None:
    """Сбрасывает соединение БД для изоляции тестов."""
    global _conn
    with _lock:
        if _conn is not None:
            _conn.close()
        _conn = None


def _conn_or_raise() -> sqlite3.Connection:
    if _conn is None:
        raise RuntimeError("База данных не инициализирована")
    return _conn


def _json_dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False)


def _json_load(value: Optional[str]) -> Any:
    if value is None:
        return None
    try:
        return json.loads(value)
    except Exception:
        return None


def _uuid() -> str:
    return str(uuid.uuid4())


def _memory_content_limit() -> int:
    raw = os.getenv("ASTRA_MEMORY_MAX_CHARS", "4000")
    try:
        limit = int(raw)
    except ValueError:
        limit = 4000
    if limit <= 0:
        return 4000
    return limit


def _reminder_row(row: sqlite3.Row) -> dict:
    return {
        "id": row["id"],
        "created_at": row["created_at"],
        "due_at": row["due_at"],
        "text": row["text"],
        "status": row["status"],
        "delivery": row["delivery"],
        "last_error": row["last_error"],
        "run_id": row["run_id"],
        "source": row["source"],
        "sent_at": row["sent_at"],
        "updated_at": row["updated_at"],
        "attempts": row["attempts"],
    }


def _infer_plan_step_kind(skill_name: str | None) -> str:
    if skill_name == "memory_save":
        return "MEMORY_COMMIT"
    if skill_name == "reminder_create":
        return "REMINDER_CREATE"
    if skill_name == "autopilot_computer":
        return "COMPUTER_ACTIONS"
    if skill_name == "web_research":
        return "WEB_RESEARCH"
    if skill_name == "report":
        return "DOCUMENT_WRITE"
    if skill_name == "extract_facts":
        return "CODE_ASSIST"
    return "COMPUTER_ACTIONS"


def _insert_fts(project_id: str, run_id: str, item_type: str, item_id: str, content: str, created_at: str, tags: Optional[str] = None) -> None:
    conn = _conn_or_raise()
    try:
        with _lock:
            conn.execute(
                "INSERT INTO memory_fts (project_id, run_id, type, item_id, content, created_at, tags) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (project_id, run_id, item_type, item_id, content, created_at, tags),
            )
            conn.commit()
    except sqlite3.OperationalError:
        # FTS-таблица не доступна
        return


def create_project(name: str, tags: list[str] | None, settings: dict | None) -> dict:
    project_id = _uuid()
    created_at = now_iso()
    updated_at = created_at
    tags_json = _json_dump(tags or [])
    settings_json = _json_dump(settings or {})

    conn = _conn_or_raise()
    with _lock:
        conn.execute(
            "INSERT INTO projects (id, name, tags, settings, created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?)",
            (project_id, name, tags_json, settings_json, created_at, updated_at),
        )
        conn.commit()

    return {
        "id": project_id,
        "name": name,
        "tags": tags or [],
        "settings": settings or {},
        "created_at": created_at,
        "updated_at": updated_at,
    }


def list_projects() -> list[dict]:
    conn = _conn_or_raise()
    rows = conn.execute("SELECT * FROM projects ORDER BY updated_at DESC").fetchall()
    return [
        {
            "id": r["id"],
            "name": r["name"],
            "tags": _json_load(r["tags"]) or [],
            "settings": _json_load(r["settings"]) or {},
            "created_at": r["created_at"],
            "updated_at": r["updated_at"],
        }
        for r in rows
    ]


def get_project(project_id: str) -> Optional[dict]:
    conn = _conn_or_raise()
    row = conn.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
    if not row:
        return None
    return {
        "id": row["id"],
        "name": row["name"],
        "tags": _json_load(row["tags"]) or [],
        "settings": _json_load(row["settings"]) or {},
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def update_project(project_id: str, name: str | None, tags: list[str] | None, settings: dict | None) -> Optional[dict]:
    project = get_project(project_id)
    if not project:
        return None
    updated_at = now_iso()
    new_name = name or project["name"]
    new_tags = tags if tags is not None else project["tags"]
    new_settings = settings if settings is not None else project["settings"]

    conn = _conn_or_raise()
    with _lock:
        conn.execute(
            "UPDATE projects SET name = ?, tags = ?, settings = ?, updated_at = ? WHERE id = ?",
            (new_name, _json_dump(new_tags), _json_dump(new_settings), updated_at, project_id),
        )
        conn.commit()

    return {
        "id": project_id,
        "name": new_name,
        "tags": new_tags,
        "settings": new_settings,
        "created_at": project["created_at"],
        "updated_at": updated_at,
    }


def create_run(
    project_id: str,
    query_text: str,
    mode: str,
    parent_run_id: Optional[str] = None,
    purpose: Optional[str] = None,
    meta: Optional[dict] = None,
) -> dict:
    run_id = _uuid()
    created_at = now_iso()
    meta_json = _json_dump(meta) if meta is not None else None
    conn = _conn_or_raise()
    with _lock:
        conn.execute(
            "INSERT INTO runs (id, project_id, query_text, mode, status, created_at, parent_run_id, purpose, meta) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (run_id, project_id, query_text, mode, "created", created_at, parent_run_id, purpose, meta_json),
        )
        conn.commit()
    return {
        "id": run_id,
        "project_id": project_id,
        "query_text": query_text,
        "mode": mode,
        "parent_run_id": parent_run_id,
        "purpose": purpose,
        "meta": meta or {},
        "status": "created",
        "created_at": created_at,
        "started_at": None,
        "finished_at": None,
    }


def get_run(run_id: str) -> Optional[dict]:
    conn = _conn_or_raise()
    row = conn.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
    if not row:
        return None
    return {
        "id": row["id"],
        "project_id": row["project_id"],
        "query_text": row["query_text"],
        "mode": row["mode"],
        "parent_run_id": row["parent_run_id"],
        "purpose": row["purpose"],
        "meta": _json_load(row["meta"]) or {},
        "status": row["status"],
        "created_at": row["created_at"],
        "started_at": row["started_at"],
        "finished_at": row["finished_at"],
    }


def update_run_meta_and_mode(run_id: str, *, mode: str, purpose: str | None, meta: dict | None) -> Optional[dict]:
    run = get_run(run_id)
    if not run:
        return None
    conn = _conn_or_raise()
    with _lock:
        conn.execute(
            "UPDATE runs SET mode = ?, purpose = ?, meta = ? WHERE id = ?",
            (mode, purpose, _json_dump(meta or {}), run_id),
        )
        conn.commit()
    return get_run(run_id)


def list_runs(project_id: str, limit: int = 50) -> list[dict]:
    conn = _conn_or_raise()
    limit = max(1, min(limit, 200))
    rows = conn.execute(
        "SELECT * FROM runs WHERE project_id = ? ORDER BY created_at DESC LIMIT ?",
        (project_id, limit),
    ).fetchall()
    return [
        {
            "id": row["id"],
            "project_id": row["project_id"],
            "query_text": row["query_text"],
            "mode": row["mode"],
            "parent_run_id": row["parent_run_id"],
            "purpose": row["purpose"],
            "meta": _json_load(row["meta"]) or {},
            "status": row["status"],
            "created_at": row["created_at"],
            "started_at": row["started_at"],
            "finished_at": row["finished_at"],
        }
        for row in rows
    ]


def _is_chat_run(run: dict) -> bool:
    meta = run.get("meta") or {}
    if meta.get("intent") == "CHAT":
        return True
    return run.get("purpose") == "chat_only"


def list_run_chain(run_id: str, limit: int = 200) -> list[dict]:
    """Возвращает цепочку запусков от корня до указанного run_id."""
    if not run_id:
        return []
    limit = max(1, min(limit, 500))
    chain: list[dict] = []
    seen: set[str] = set()
    current_id: Optional[str] = run_id
    while current_id and current_id not in seen and len(chain) < limit:
        seen.add(current_id)
        run = get_run(current_id)
        if not run:
            break
        chain.append(run)
        current_id = run.get("parent_run_id")
    chain.reverse()
    return chain


def get_latest_event_by_type(run_id: str, event_type: str) -> Optional[dict]:
    conn = _conn_or_raise()
    row = conn.execute(
        "SELECT rowid, * FROM events WHERE run_id = ? AND type = ? ORDER BY rowid DESC LIMIT 1",
        (run_id, event_type),
    ).fetchone()
    if not row:
        return None
    return {
        "seq": row["rowid"],
        "id": row["id"],
        "run_id": row["run_id"],
        "ts": row["ts"],
        "type": row["type"],
        "level": row["level"],
        "message": row["message"],
        "payload": _json_load(row["payload"]) or {},
        "task_id": row["task_id"],
        "step_id": row["step_id"],
    }


def list_recent_chat_turns(anchor_run_id: str | None, limit_turns: int = 20) -> list[dict]:
    """Возвращает историю чата (user/assistant) для цепочки запусков до anchor_run_id включительно."""
    if not anchor_run_id:
        return []
    limit_turns = max(1, min(limit_turns, 100))
    chain = list_run_chain(anchor_run_id, limit=limit_turns * 5)
    chat_runs = [run for run in chain if _is_chat_run(run)]
    if len(chat_runs) > limit_turns:
        chat_runs = chat_runs[-limit_turns:]
    history: list[dict] = []
    for run in chat_runs:
        user_text = run.get("query_text") or ""
        if user_text:
            history.append(
                {
                    "role": "user",
                    "content": user_text,
                    "ts": run.get("created_at"),
                    "run_id": run.get("id"),
                }
            )
        event = get_latest_event_by_type(run.get("id"), "chat_response_generated")
        if event:
            payload = event.get("payload") or {}
            text = payload.get("text")
            if text:
                history.append(
                    {
                        "role": "assistant",
                        "content": text,
                        "ts": event.get("ts"),
                        "run_id": run.get("id"),
                    }
                )
    return history


def create_reminder(
    due_at: str,
    text: str,
    *,
    delivery: str,
    status: str = "pending",
    run_id: str | None = None,
    source: str | None = None,
) -> dict:
    reminder_id = _uuid()
    created_at = now_iso()
    updated_at = created_at
    conn = _conn_or_raise()
    with _lock:
        conn.execute(
            """
            INSERT INTO reminders (id, created_at, due_at, text, status, delivery, last_error, run_id, source, sent_at, updated_at, attempts)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (reminder_id, created_at, due_at, text, status, delivery, None, run_id, source, None, updated_at, 0),
        )
        conn.commit()
    return {
        "id": reminder_id,
        "created_at": created_at,
        "due_at": due_at,
        "text": text,
        "status": status,
        "delivery": delivery,
        "last_error": None,
        "run_id": run_id,
        "source": source,
        "sent_at": None,
        "updated_at": updated_at,
        "attempts": 0,
    }


def list_reminders(status: str | None = None, limit: int = 200) -> list[dict]:
    conn = _conn_or_raise()
    limit = max(1, min(limit, 500))
    if status:
        rows = conn.execute(
            "SELECT * FROM reminders WHERE status = ? ORDER BY due_at ASC LIMIT ?",
            (status, limit),
        ).fetchall()
    else:
        rows = conn.execute("SELECT * FROM reminders ORDER BY due_at DESC LIMIT ?", (limit,)).fetchall()
    return [_reminder_row(r) for r in rows]


def get_reminder(reminder_id: str) -> dict | None:
    conn = _conn_or_raise()
    row = conn.execute("SELECT * FROM reminders WHERE id = ?", (reminder_id,)).fetchone()
    if not row:
        return None
    return _reminder_row(row)


def cancel_reminder(reminder_id: str) -> dict | None:
    conn = _conn_or_raise()
    updated_at = now_iso()
    with _lock:
        row = conn.execute("SELECT * FROM reminders WHERE id = ?", (reminder_id,)).fetchone()
        if not row:
            return None
        conn.execute(
            "UPDATE reminders SET status = ?, updated_at = ? WHERE id = ?",
            ("cancelled", updated_at, reminder_id),
        )
        conn.commit()
    updated = dict(_reminder_row(row))
    updated["status"] = "cancelled"
    updated["updated_at"] = updated_at
    return updated


def claim_due_reminders(now_ts: str, limit: int = 20) -> list[dict]:
    conn = _conn_or_raise()
    limit = max(1, min(limit, 200))
    claimed: list[dict] = []
    with _lock:
        rows = conn.execute(
            "SELECT * FROM reminders WHERE status = 'pending' AND due_at <= ? ORDER BY due_at ASC LIMIT ?",
            (now_ts, limit),
        ).fetchall()
        for row in rows:
            updated_at = now_iso()
            res = conn.execute(
                "UPDATE reminders SET status = ?, updated_at = ?, attempts = attempts + 1 WHERE id = ? AND status = 'pending'",
                ("sending", updated_at, row["id"]),
            )
            if res.rowcount == 0:
                continue
            conn.commit()
            data = _reminder_row(row)
            data["status"] = "sending"
            data["updated_at"] = updated_at
            data["attempts"] = (row["attempts"] or 0) + 1
            claimed.append(data)
    return claimed


def mark_reminder_sent(reminder_id: str, delivery: str) -> dict | None:
    conn = _conn_or_raise()
    sent_at = now_iso()
    with _lock:
        row = conn.execute("SELECT * FROM reminders WHERE id = ?", (reminder_id,)).fetchone()
        if not row:
            return None
        conn.execute(
            "UPDATE reminders SET status = ?, delivery = ?, sent_at = ?, last_error = ?, updated_at = ? WHERE id = ?",
            ("sent", delivery, sent_at, None, sent_at, reminder_id),
        )
        conn.commit()
    updated = dict(_reminder_row(row))
    updated.update({"status": "sent", "delivery": delivery, "sent_at": sent_at, "last_error": None, "updated_at": sent_at})
    return updated


def mark_reminder_failed(reminder_id: str, error: str, delivery: str) -> dict | None:
    conn = _conn_or_raise()
    updated_at = now_iso()
    with _lock:
        row = conn.execute("SELECT * FROM reminders WHERE id = ?", (reminder_id,)).fetchone()
        if not row:
            return None
        conn.execute(
            "UPDATE reminders SET status = ?, delivery = ?, last_error = ?, updated_at = ? WHERE id = ?",
            ("failed", delivery, error, updated_at, reminder_id),
        )
        conn.commit()
    updated = dict(_reminder_row(row))
    updated.update({"status": "failed", "delivery": delivery, "last_error": error, "updated_at": updated_at})
    return updated


def update_run_status(run_id: str, status: str, started_at: Optional[str] = None, finished_at: Optional[str] = None) -> None:
    conn = _conn_or_raise()
    with _lock:
        conn.execute(
            "UPDATE runs SET status = ?, started_at = COALESCE(?, started_at), finished_at = COALESCE(?, finished_at) WHERE id = ?",
            (status, started_at, finished_at, run_id),
        )
        conn.commit()


def insert_plan_steps(run_id: str, steps: list[dict]) -> list[dict]:
    conn = _conn_or_raise()
    with _lock:
        conn.execute("DELETE FROM plan_steps WHERE run_id = ?", (run_id,))
        for step in steps:
            kind = step.get("kind") or _infer_plan_step_kind(step.get("skill_name"))
            conn.execute(
                "INSERT INTO plan_steps (id, run_id, step_index, title, skill_name, inputs, depends_on, status, kind, success_criteria, success_checks, danger_flags, requires_approval, artifacts_expected) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    step["id"],
                    run_id,
                    step["step_index"],
                    step["title"],
                    step["skill_name"],
                    _json_dump(step.get("inputs") or {}),
                    _json_dump(step.get("depends_on") or []),
                    step.get("status", "created"),
                    kind,
                    _json_dump(step.get("success_criteria") or ""),
                    _json_dump(step.get("success_checks") or []),
                    _json_dump(step.get("danger_flags") or []),
                    1 if step.get("requires_approval") else 0,
                    _json_dump(step.get("artifacts_expected") or []),
                ),
            )
        conn.commit()
    return steps


def list_plan_steps(run_id: str) -> list[dict]:
    conn = _conn_or_raise()
    rows = conn.execute(
        "SELECT * FROM plan_steps WHERE run_id = ? ORDER BY step_index ASC",
        (run_id,),
    ).fetchall()
    return [
        {
            "id": r["id"],
            "run_id": r["run_id"],
            "step_index": r["step_index"],
            "title": r["title"],
            "skill_name": r["skill_name"],
            "inputs": _json_load(r["inputs"]) or {},
            "depends_on": _json_load(r["depends_on"]) or [],
            "status": r["status"],
            "kind": r["kind"] or _infer_plan_step_kind(r["skill_name"]),
            "success_criteria": _json_load(r["success_criteria"]) or "",
            "success_checks": _json_load(r["success_checks"]) or [],
            "danger_flags": _json_load(r["danger_flags"]) or [],
            "requires_approval": bool(r["requires_approval"]) if r["requires_approval"] is not None else False,
            "artifacts_expected": _json_load(r["artifacts_expected"]) or [],
        }
        for r in rows
    ]


def get_plan_step(step_id: str) -> Optional[dict]:
    conn = _conn_or_raise()
    row = conn.execute("SELECT * FROM plan_steps WHERE id = ?", (step_id,)).fetchone()
    if not row:
        return None
    return {
        "id": row["id"],
        "run_id": row["run_id"],
        "step_index": row["step_index"],
        "title": row["title"],
        "skill_name": row["skill_name"],
        "inputs": _json_load(row["inputs"]) or {},
        "depends_on": _json_load(row["depends_on"]) or [],
        "status": row["status"],
        "kind": row["kind"] or _infer_plan_step_kind(row["skill_name"]),
        "success_criteria": _json_load(row["success_criteria"]) or "",
        "success_checks": _json_load(row["success_checks"]) or [],
        "danger_flags": _json_load(row["danger_flags"]) or [],
        "requires_approval": bool(row["requires_approval"]) if row["requires_approval"] is not None else False,
        "artifacts_expected": _json_load(row["artifacts_expected"]) or [],
    }


def update_plan_step_status(step_id: str, status: str) -> None:
    conn = _conn_or_raise()
    with _lock:
        conn.execute(
            "UPDATE plan_steps SET status = ? WHERE id = ?",
            (status, step_id),
        )
        conn.commit()


def create_task(run_id: str, plan_step_id: str, attempt: int) -> dict:
    task_id = _uuid()
    conn = _conn_or_raise()
    with _lock:
        conn.execute(
            "INSERT INTO tasks (id, run_id, plan_step_id, attempt, status) VALUES (?, ?, ?, ?, ?)",
            (task_id, run_id, plan_step_id, attempt, "queued"),
        )
        conn.commit()
    return {
        "id": task_id,
        "run_id": run_id,
        "plan_step_id": plan_step_id,
        "attempt": attempt,
        "status": "queued",
        "started_at": None,
        "finished_at": None,
        "error": None,
        "duration_ms": None,
    }


def update_task_status(task_id: str, status: str, started_at: Optional[str] = None, finished_at: Optional[str] = None, error: Optional[str] = None, duration_ms: Optional[int] = None) -> None:
    conn = _conn_or_raise()
    with _lock:
        conn.execute(
            """
            UPDATE tasks
            SET status = ?,
                started_at = COALESCE(?, started_at),
                finished_at = COALESCE(?, finished_at),
                error = COALESCE(?, error),
                duration_ms = COALESCE(?, duration_ms)
            WHERE id = ?
            """,
            (status, started_at, finished_at, error, duration_ms, task_id),
        )
        conn.commit()


def list_tasks(run_id: str) -> list[dict]:
    conn = _conn_or_raise()
    rows = conn.execute(
        "SELECT * FROM tasks WHERE run_id = ? ORDER BY rowid ASC",
        (run_id,),
    ).fetchall()
    return [
        {
            "id": r["id"],
            "run_id": r["run_id"],
            "plan_step_id": r["plan_step_id"],
            "attempt": r["attempt"],
            "status": r["status"],
            "started_at": r["started_at"],
            "finished_at": r["finished_at"],
            "error": r["error"],
            "duration_ms": r["duration_ms"],
        }
        for r in rows
    ]


def get_task(task_id: str) -> Optional[dict]:
    conn = _conn_or_raise()
    row = conn.execute("SELECT * FROM tasks WHERE id = ?", (task_id,)).fetchone()
    if not row:
        return None
    return {
        "id": row["id"],
        "run_id": row["run_id"],
        "plan_step_id": row["plan_step_id"],
        "attempt": row["attempt"],
        "status": row["status"],
        "started_at": row["started_at"],
        "finished_at": row["finished_at"],
        "error": row["error"],
        "duration_ms": row["duration_ms"],
    }


def list_tasks_for_step(run_id: str, step_id: str) -> list[dict]:
    conn = _conn_or_raise()
    rows = conn.execute(
        "SELECT * FROM tasks WHERE run_id = ? AND plan_step_id = ? ORDER BY attempt ASC",
        (run_id, step_id),
    ).fetchall()
    return [
        {
            "id": r["id"],
            "run_id": r["run_id"],
            "plan_step_id": r["plan_step_id"],
            "attempt": r["attempt"],
            "status": r["status"],
            "started_at": r["started_at"],
            "finished_at": r["finished_at"],
            "error": r["error"],
            "duration_ms": r["duration_ms"],
        }
        for r in rows
    ]


def get_last_task_for_step(run_id: str, step_id: str) -> Optional[dict]:
    conn = _conn_or_raise()
    row = conn.execute(
        "SELECT * FROM tasks WHERE run_id = ? AND plan_step_id = ? ORDER BY attempt DESC LIMIT 1",
        (run_id, step_id),
    ).fetchone()
    if not row:
        return None
    return {
        "id": row["id"],
        "run_id": row["run_id"],
        "plan_step_id": row["plan_step_id"],
        "attempt": row["attempt"],
        "status": row["status"],
        "started_at": row["started_at"],
        "finished_at": row["finished_at"],
        "error": row["error"],
        "duration_ms": row["duration_ms"],
    }


def next_task_attempt(run_id: str, step_id: str) -> int:
    conn = _conn_or_raise()
    row = conn.execute(
        "SELECT MAX(attempt) AS max_attempt FROM tasks WHERE run_id = ? AND plan_step_id = ?",
        (run_id, step_id),
    ).fetchone()
    max_attempt = row["max_attempt"] if row and row["max_attempt"] is not None else 0
    return int(max_attempt) + 1


def insert_sources(run_id: str, sources: list[dict]) -> list[dict]:
    conn = _conn_or_raise()
    run = get_run(run_id)
    project_id = run["project_id"] if run else ""
    with _lock:
        for s in sources:
            conn.execute(
                "INSERT INTO sources (id, run_id, url, title, domain, quality, retrieved_at, snippet, pinned) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    s["id"],
                    run_id,
                    s["url"],
                    s.get("title"),
                    s.get("domain"),
                    s.get("quality"),
                    s.get("retrieved_at"),
                    s.get("snippet"),
                    1 if s.get("pinned") else 0,
                ),
            )
        conn.commit()
    for s in sources:
        content = " ".join([str(s.get("title") or ""), str(s.get("url") or ""), str(s.get("snippet") or "")]).strip()
        if project_id:
            _insert_fts(project_id, run_id, "source", s["id"], content, s.get("retrieved_at") or now_iso())
    return sources


def list_sources(run_id: str) -> list[dict]:
    conn = _conn_or_raise()
    rows = conn.execute("SELECT * FROM sources WHERE run_id = ?", (run_id,)).fetchall()
    return [
        {
            "id": r["id"],
            "run_id": r["run_id"],
            "url": r["url"],
            "title": r["title"],
            "domain": r["domain"],
            "quality": r["quality"],
            "retrieved_at": r["retrieved_at"],
            "snippet": r["snippet"],
            "pinned": bool(r["pinned"]),
        }
        for r in rows
    ]


def insert_facts(run_id: str, facts: list[dict]) -> list[dict]:
    conn = _conn_or_raise()
    run = get_run(run_id)
    project_id = run["project_id"] if run else ""
    with _lock:
        for f in facts:
            conn.execute(
                "INSERT INTO facts (id, run_id, key, value, confidence, source_ids, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    f["id"],
                    run_id,
                    f["key"],
                    _json_dump(f["value"]),
                    f.get("confidence", 0.0),
                    _json_dump(f.get("source_ids") or []),
                    f["created_at"],
                ),
            )
        conn.commit()
    for f in facts:
        content = " ".join([str(f.get("key") or ""), _json_dump(f.get("value"))]).strip()
        if project_id:
            _insert_fts(project_id, run_id, "fact", f["id"], content, f.get("created_at") or now_iso())
    return facts


def list_facts(run_id: str) -> list[dict]:
    conn = _conn_or_raise()
    rows = conn.execute("SELECT * FROM facts WHERE run_id = ?", (run_id,)).fetchall()
    return [
        {
            "id": r["id"],
            "run_id": r["run_id"],
            "key": r["key"],
            "value": _json_load(r["value"]),
            "confidence": r["confidence"],
            "source_ids": _json_load(r["source_ids"]) or [],
            "created_at": r["created_at"],
        }
        for r in rows
    ]


def insert_conflicts(run_id: str, conflicts: list[dict]) -> list[dict]:
    conn = _conn_or_raise()
    with _lock:
        for c in conflicts:
            conn.execute(
                "INSERT INTO conflicts (id, run_id, fact_key, group_json, status) VALUES (?, ?, ?, ?, ?)",
                (
                    c["id"],
                    run_id,
                    c["fact_key"],
                    _json_dump(c["group"]),
                    c["status"],
                ),
            )
        conn.commit()
    return conflicts


def list_conflicts(run_id: str) -> list[dict]:
    conn = _conn_or_raise()
    rows = conn.execute("SELECT * FROM conflicts WHERE run_id = ?", (run_id,)).fetchall()
    return [
        {
            "id": r["id"],
            "run_id": r["run_id"],
            "fact_key": r["fact_key"],
            "group": _json_load(r["group_json"]) or {},
            "status": r["status"],
        }
        for r in rows
    ]


def get_conflict(conflict_id: str) -> Optional[dict]:
    conn = _conn_or_raise()
    row = conn.execute("SELECT * FROM conflicts WHERE id = ?", (conflict_id,)).fetchone()
    if not row:
        return None
    return {
        "id": row["id"],
        "run_id": row["run_id"],
        "fact_key": row["fact_key"],
        "group": _json_load(row["group_json"]) or [],
        "status": row["status"],
    }


def insert_artifacts(run_id: str, artifacts: list[dict]) -> list[dict]:
    conn = _conn_or_raise()
    run = get_run(run_id)
    project_id = run["project_id"] if run else ""
    with _lock:
        for a in artifacts:
            conn.execute(
                "INSERT INTO artifacts (id, run_id, type, title, content_uri, created_at, meta) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    a["id"],
                    run_id,
                    a["type"],
                    a["title"],
                    a["content_uri"],
                    a["created_at"],
                    _json_dump(a.get("meta") or {}),
                ),
            )
        conn.commit()
    for a in artifacts:
        content = " ".join([str(a.get("title") or ""), str(a.get("content_uri") or ""), _json_dump(a.get("meta") or {})]).strip()
        if project_id:
            _insert_fts(project_id, run_id, "artifact", a["id"], content, a.get("created_at") or now_iso())
    return artifacts


def list_artifacts(run_id: str) -> list[dict]:
    conn = _conn_or_raise()
    rows = conn.execute("SELECT * FROM artifacts WHERE run_id = ?", (run_id,)).fetchall()
    return [
        {
            "id": r["id"],
            "run_id": r["run_id"],
            "type": r["type"],
            "title": r["title"],
            "content_uri": r["content_uri"],
            "created_at": r["created_at"],
            "meta": _json_load(r["meta"]) or {},
        }
        for r in rows
    ]


def get_artifact(artifact_id: str) -> Optional[dict]:
    conn = _conn_or_raise()
    row = conn.execute("SELECT * FROM artifacts WHERE id = ?", (artifact_id,)).fetchone()
    if not row:
        return None
    return {
        "id": row["id"],
        "run_id": row["run_id"],
        "type": row["type"],
        "title": row["title"],
        "content_uri": row["content_uri"],
        "created_at": row["created_at"],
        "meta": _json_load(row["meta"]) or {},
    }


def get_source(source_id: str) -> Optional[dict]:
    conn = _conn_or_raise()
    row = conn.execute("SELECT * FROM sources WHERE id = ?", (source_id,)).fetchone()
    if not row:
        return None
    return {
        "id": row["id"],
        "run_id": row["run_id"],
        "url": row["url"],
        "title": row["title"],
        "domain": row["domain"],
        "quality": row["quality"],
        "retrieved_at": row["retrieved_at"],
        "snippet": row["snippet"],
        "pinned": bool(row["pinned"]),
    }


def get_fact(fact_id: str) -> Optional[dict]:
    conn = _conn_or_raise()
    row = conn.execute("SELECT * FROM facts WHERE id = ?", (fact_id,)).fetchone()
    if not row:
        return None
    return {
        "id": row["id"],
        "run_id": row["run_id"],
        "key": row["key"],
        "value": _json_load(row["value"]),
        "confidence": row["confidence"],
        "source_ids": _json_load(row["source_ids"]) or [],
        "created_at": row["created_at"],
    }


def create_approval(
    run_id: str,
    task_id: str,
    scope: str,
    title: str,
    description: str,
    proposed_actions: list[dict],
    decision: dict | None = None,
    *,
    step_id: str | None = None,
    approval_type: str | None = None,
    preview: dict | None = None,
) -> dict:
    approval_id = _uuid()
    created_at = now_iso()
    conn = _conn_or_raise()
    if approval_type is None:
        approval_type = "ACCOUNT_CHANGE"
    if preview is None:
        preview = {
            "summary": title,
            "details": {},
            "risk": "Опасное действие",
            "suggested_user_action": "Подтвердите выполнение",
            "expires_in_ms": None,
        }
    preview_json = _json_dump(preview) if preview is not None else None
    with _lock:
        conn.execute(
            """
            INSERT INTO approvals (id, run_id, task_id, created_at, scope, title, description, proposed_actions, status, decision_json, step_id, approval_type, preview_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                approval_id,
                run_id,
                task_id,
                created_at,
                scope,
                title,
                description,
                _json_dump(proposed_actions),
                "pending",
                _json_dump(decision) if decision else None,
                step_id,
                approval_type,
                preview_json,
            ),
        )
        conn.commit()
    return {
        "id": approval_id,
        "run_id": run_id,
        "task_id": task_id,
        "step_id": step_id,
        "created_at": created_at,
        "scope": scope,
        "approval_type": approval_type,
        "title": title,
        "description": description,
        "proposed_actions": proposed_actions,
        "preview": preview,
        "status": "pending",
        "decided_at": None,
        "resolved_at": None,
        "decided_by": None,
        "decision": decision,
    }


def list_approvals(run_id: str) -> list[dict]:
    conn = _conn_or_raise()
    rows = conn.execute("SELECT * FROM approvals WHERE run_id = ? ORDER BY created_at DESC", (run_id,)).fetchall()
    return [
        {
            "id": r["id"],
            "run_id": r["run_id"],
            "task_id": r["task_id"],
            "step_id": r["step_id"] if "step_id" in r.keys() else None,
            "created_at": r["created_at"],
            "scope": r["scope"],
            "approval_type": r["approval_type"] if "approval_type" in r.keys() else None,
            "title": r["title"],
            "description": r["description"],
            "proposed_actions": _json_load(r["proposed_actions"]) or [],
            "status": r["status"],
            "decided_at": r["decided_at"],
            "resolved_at": r["decided_at"],
            "decided_by": r["decided_by"],
            "decision": _json_load(r["decision_json"]) if "decision_json" in r.keys() else None,
            "preview": _json_load(r["preview_json"]) if "preview_json" in r.keys() else None,
        }
        for r in rows
    ]


def get_approval(approval_id: str) -> Optional[dict]:
    conn = _conn_or_raise()
    row = conn.execute("SELECT * FROM approvals WHERE id = ?", (approval_id,)).fetchone()
    if not row:
        return None
    return {
        "id": row["id"],
        "run_id": row["run_id"],
        "task_id": row["task_id"],
        "step_id": row["step_id"] if "step_id" in row.keys() else None,
        "created_at": row["created_at"],
        "scope": row["scope"],
        "approval_type": row["approval_type"] if "approval_type" in row.keys() else None,
        "title": row["title"],
        "description": row["description"],
        "proposed_actions": _json_load(row["proposed_actions"]) or [],
        "status": row["status"],
        "decided_at": row["decided_at"],
        "resolved_at": row["decided_at"],
        "decided_by": row["decided_by"],
        "decision": _json_load(row["decision_json"]) if "decision_json" in row.keys() else None,
        "preview": _json_load(row["preview_json"]) if "preview_json" in row.keys() else None,
    }


def update_approval_status(approval_id: str, status: str, decided_by: str, decision: dict | None = None) -> Optional[dict]:
    approval = get_approval(approval_id)
    if not approval:
        return None
    decided_at = now_iso()
    conn = _conn_or_raise()
    with _lock:
        conn.execute(
            "UPDATE approvals SET status = ?, decided_at = ?, decided_by = ?, decision_json = ? WHERE id = ?",
            (status, decided_at, decided_by, _json_dump(decision) if decision else None, approval_id),
        )
        conn.commit()
    approval["status"] = status
    approval["decided_at"] = decided_at
    approval["resolved_at"] = decided_at
    approval["decided_by"] = decided_by
    approval["decision"] = decision
    return approval


def set_session_token_hash(token_hash: str, salt: str) -> None:
    conn = _conn_or_raise()
    with _lock:
        conn.execute(
            "INSERT OR REPLACE INTO session_tokens (id, token_hash, salt, created_at) VALUES (?, ?, ?, ?)",
            ("default", token_hash, salt, now_iso()),
        )
        conn.commit()


def get_session_token_hash() -> Optional[dict]:
    conn = _conn_or_raise()
    row = conn.execute("SELECT * FROM session_tokens WHERE id = ?", ("default",)).fetchone()
    if not row:
        return None
    return {"token_hash": row["token_hash"], "salt": row["salt"], "created_at": row["created_at"]}


def search_memory(project_id: str, query: str, item_type: Optional[str] = None, from_ts: Optional[str] = None, to_ts: Optional[str] = None, tags: Optional[str] = None, limit: int = 50) -> list[dict]:
    conn = _conn_or_raise()
    results: list[dict] = []
    if not query:
        return results

    try:
        rows = conn.execute(
            """
            SELECT project_id, run_id, type, item_id, content, created_at, tags
            FROM memory_fts
            WHERE project_id = ? AND memory_fts MATCH ?
            LIMIT ?
            """,
            (project_id, query, limit),
        ).fetchall()
        for r in rows:
            if item_type and r["type"] != item_type:
                continue
            item = None
            if r["type"] == "source":
                item = get_source(r["item_id"])
            elif r["type"] == "fact":
                item = get_fact(r["item_id"])
            elif r["type"] == "artifact":
                item = get_artifact(r["item_id"])
            if not item:
                continue
            results.append({"type": r["type"], "item": item})
    except sqlite3.OperationalError:
        # запасной вариант через LIKE
        q = f"%{query}%"
        if item_type in (None, "source"):
            rows = conn.execute("SELECT * FROM sources WHERE run_id IN (SELECT id FROM runs WHERE project_id = ?) AND (url LIKE ? OR title LIKE ? OR snippet LIKE ?)", (project_id, q, q, q)).fetchall()
            for r in rows:
                results.append({"type": "source", "item": get_source(r["id"])})
        if item_type in (None, "fact"):
            rows = conn.execute("SELECT * FROM facts WHERE run_id IN (SELECT id FROM runs WHERE project_id = ?) AND (key LIKE ? OR value LIKE ?)", (project_id, q, q)).fetchall()
            for r in rows:
                results.append({"type": "fact", "item": get_fact(r["id"])})
        if item_type in (None, "artifact"):
            rows = conn.execute("SELECT * FROM artifacts WHERE run_id IN (SELECT id FROM runs WHERE project_id = ?) AND (title LIKE ? OR content_uri LIKE ?)", (project_id, q, q)).fetchall()
            for r in rows:
                results.append({"type": "artifact", "item": get_artifact(r["id"])})

    # фильтры tags/from/to не индексируются — применяем после выборки
    filtered: list[dict] = []
    for result in results:
        item = result["item"]
        created_at = item.get("created_at") or item.get("retrieved_at")
        if from_ts and created_at and created_at < from_ts:
            continue
        if to_ts and created_at and created_at > to_ts:
            continue
        if tags:
            tag_text = _json_dump(item.get("meta") or {})
            if tags not in tag_text:
                continue
        filtered.append(result)
    return filtered[:limit]


def create_user_memory(
    title: Optional[str],
    content: str,
    tags: Optional[list[str]] = None,
    source: str = "user_command",
    meta: Optional[dict] = None,
) -> dict:
    if not isinstance(content, str) or not content.strip():
        raise ValueError("content_required")
    limit = _memory_content_limit()
    if len(content) > limit:
        raise ValueError(f"content_too_long:{limit}")

    title_text = (title or "").strip()
    if not title_text:
        title_text = content.strip().splitlines()[0] if content.strip() else "Память пользователя"
    if len(title_text) > 120:
        title_text = title_text[:117] + "..."

    tags = tags or []
    created_at = now_iso()
    updated_at = created_at
    memory_id = _uuid()

    conn = _conn_or_raise()
    with _lock:
        conn.execute(
            """
            INSERT INTO user_memories (id, created_at, updated_at, title, content, tags, source, is_deleted, pinned, last_used_at, meta)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                memory_id,
                created_at,
                updated_at,
                title_text,
                content,
                _json_dump(tags),
                source,
                0,
                0,
                None,
                _json_dump(meta or {}),
            ),
        )
        conn.commit()
    return {
        "id": memory_id,
        "created_at": created_at,
        "updated_at": updated_at,
        "title": title_text,
        "content": content,
        "tags": tags,
        "source": source,
        "is_deleted": False,
        "pinned": False,
        "last_used_at": None,
        "meta": meta or {},
    }


def list_user_memories(query: str | None = None, tag: str | None = None, limit: int = 50, include_deleted: bool = False) -> list[dict]:
    conn = _conn_or_raise()
    query = (query or "").strip()
    tag = (tag or "").strip()
    params: list[Any] = []
    clauses: list[str] = []
    if not include_deleted:
        clauses.append("is_deleted = 0")
    if query:
        clauses.append("(title LIKE ? OR content LIKE ?)")
        like = f"%{query}%"
        params.extend([like, like])
    if tag:
        clauses.append("tags LIKE ?")
        params.append(f"%{tag}%")
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    limit = max(1, min(limit, 200))

    rows = conn.execute(
        f"""
        SELECT * FROM user_memories
        {where}
        ORDER BY pinned DESC, updated_at DESC
        LIMIT ?
        """,
        (*params, limit),
    ).fetchall()

    return [
        {
            "id": r["id"],
            "created_at": r["created_at"],
            "updated_at": r["updated_at"],
            "title": r["title"],
            "content": r["content"],
            "tags": _json_load(r["tags"]) or [],
            "source": r["source"],
            "is_deleted": bool(r["is_deleted"]),
            "pinned": bool(r["pinned"]),
            "last_used_at": r["last_used_at"],
            "meta": _json_load(r["meta"]) if "meta" in r.keys() else {},
        }
        for r in rows
    ]


def get_user_memory(memory_id: str) -> Optional[dict]:
    conn = _conn_or_raise()
    row = conn.execute("SELECT * FROM user_memories WHERE id = ?", (memory_id,)).fetchone()
    if not row:
        return None
    return {
        "id": row["id"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "title": row["title"],
        "content": row["content"],
        "tags": _json_load(row["tags"]) or [],
        "source": row["source"],
        "is_deleted": bool(row["is_deleted"]),
        "pinned": bool(row["pinned"]),
        "last_used_at": row["last_used_at"],
        "meta": _json_load(row["meta"]) if "meta" in row.keys() else {},
    }


def delete_user_memory(memory_id: str) -> Optional[dict]:
    memory = get_user_memory(memory_id)
    if not memory:
        return None
    conn = _conn_or_raise()
    with _lock:
        conn.execute(
            "UPDATE user_memories SET is_deleted = 1, updated_at = ? WHERE id = ?",
            (now_iso(), memory_id),
        )
        conn.commit()
    memory["is_deleted"] = True
    return memory


def set_user_memory_pinned(memory_id: str, pinned: bool) -> Optional[dict]:
    memory = get_user_memory(memory_id)
    if not memory:
        return None
    conn = _conn_or_raise()
    with _lock:
        conn.execute(
            "UPDATE user_memories SET pinned = ?, updated_at = ? WHERE id = ?",
            (1 if pinned else 0, now_iso(), memory_id),
        )
        conn.commit()
    memory["pinned"] = pinned
    return memory


def insert_event(event: dict) -> dict:
    conn = _conn_or_raise()
    with _lock:
        conn.execute(
            "INSERT INTO events (id, run_id, ts, type, level, message, payload, task_id, step_id) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                event["id"],
                event["run_id"],
                event["ts"],
                event["type"],
                event["level"],
                event["message"],
                _json_dump(event.get("payload") or {}),
                event.get("task_id"),
                event.get("step_id"),
            ),
        )
        conn.commit()
    return event


def list_events(run_id: str, limit: int = 500) -> list[dict]:
    conn = _conn_or_raise()
    rows = conn.execute(
        "SELECT rowid, * FROM events WHERE run_id = ? ORDER BY rowid ASC LIMIT ?",
        (run_id, limit),
    ).fetchall()
    return [
        {
            "seq": r["rowid"],
            "id": r["id"],
            "run_id": r["run_id"],
            "ts": r["ts"],
            "type": r["type"],
            "level": r["level"],
            "message": r["message"],
            "payload": _json_load(r["payload"]) or {},
            "task_id": r["task_id"],
            "step_id": r["step_id"],
        }
        for r in rows
    ]


def list_events_since(run_id: str, last_seq: int) -> list[dict]:
    conn = _conn_or_raise()
    rows = conn.execute(
        "SELECT rowid, * FROM events WHERE run_id = ? AND rowid > ? ORDER BY rowid ASC",
        (run_id, last_seq),
    ).fetchall()
    return [
        {
            "seq": r["rowid"],
            "id": r["id"],
            "run_id": r["run_id"],
            "ts": r["ts"],
            "type": r["type"],
            "level": r["level"],
            "message": r["message"],
            "payload": _json_load(r["payload"]) or {},
            "task_id": r["task_id"],
            "step_id": r["step_id"],
        }
        for r in rows
    ]


def add_event(run_id: str, event_type: str, level: str, message: str, payload: dict | None = None, task_id: Optional[str] = None, step_id: Optional[str] = None) -> dict:
    event = {
        "id": _uuid(),
        "run_id": run_id,
        "ts": int(datetime.utcnow().timestamp() * 1000),
        "type": event_type,
        "level": level,
        "message": message,
        "payload": payload or {},
        "task_id": task_id,
        "step_id": step_id,
    }
    return insert_event(event)

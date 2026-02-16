from __future__ import annotations

import json
import os
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from apps.api.main import create_app
from memory import store


def make_client() -> TestClient:
    temp_dir = Path(tempfile.mkdtemp())
    os.environ["ASTRA_DATA_DIR"] = str(temp_dir)
    store.reset_for_tests()
    return TestClient(create_app())

def _load_auth_token() -> str | None:
    data_dir = Path(os.environ.get("ASTRA_DATA_DIR", ROOT / ".astra"))
    token_path = data_dir / "auth.token"
    if not token_path.exists():
        return None
    token = token_path.read_text(encoding="utf-8").strip()
    return token or None


def bootstrap(client: TestClient, token: str = "test-token") -> dict:
    file_token = _load_auth_token()
    token = file_token or token
    res = client.post("/api/v1/auth/bootstrap", json={"token": token})
    if res.status_code == 409 and file_token:
        token = file_token
    return {"Authorization": f"Bearer {token}", "X-Astra-QA-Mode": "1"}


def _auth_token_from_headers(headers: dict) -> str:
    auth = headers.get("Authorization", "")
    return auth.replace("Bearer ", "", 1).strip()


def unwrap_run(payload: dict) -> dict:
    return payload.get("run") or payload


def wait_for_run_done(client: TestClient, run_id: str, headers: dict, timeout: float = 10.0):
    start = time.time()
    while time.time() - start < timeout:
        res = client.get(f"/api/v1/runs/{run_id}", headers=headers)
        res.raise_for_status()
        status = res.json()["status"]
        if status in ("done", "failed", "canceled"):
            return status
        time.sleep(0.2)
    return "timeout"


def wait_for_pending_approval(client: TestClient, run_id: str, headers: dict, timeout: float = 5.0):
    start = time.time()
    while time.time() - start < timeout:
        approvals = client.get(f"/api/v1/runs/{run_id}/approvals", headers=headers).json()
        pending = [a for a in approvals if a.get("status") == "pending"]
        if pending:
            return pending[0]["id"]
        time.sleep(0.2)
    return None


class BridgeHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length).decode("utf-8")
        if self.path == "/shell/execute":
            payload = json.loads(body)
            response = {"output": f"выполнено {payload.get('command')}"}
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(json.dumps(response).encode("utf-8"))
            return
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(b"{}")


def start_bridge_server(port: int):
    try:
        server = HTTPServer(("127.0.0.1", port), BridgeHandler)
    except PermissionError:
        import pytest

        pytest.skip("sandbox blocks local TCP bind")
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server


def test_smoke_flow():
    client = make_client()
    headers = bootstrap(client)
    token = _auth_token_from_headers(headers)

    project = client.post("/api/v1/projects", json={"name": "Проверка", "tags": [], "settings": {}}, headers=headers).json()
    run = client.post(
        f"/api/v1/projects/{project['id']}/runs",
        json={"query_text": "Проверь сайт https://example.com в браузере", "mode": "research"},
        headers=headers,
    ).json()
    run = unwrap_run(run)

    # вручную задаём план для smoke-теста, чтобы не зависеть от автопилота
    plan_steps = [
        {
            "id": "step-0",
            "step_index": 0,
            "title": "Сбор источников",
            "skill_name": "web_research",
            "inputs": {"query": "https://example.com"},
            "depends_on": [],
            "status": "created",
        },
        {
            "id": "step-1",
            "step_index": 1,
            "title": "Извлечь факты",
            "skill_name": "extract_facts",
            "inputs": {},
            "depends_on": [0],
            "status": "created",
        },
        {
            "id": "step-2",
            "step_index": 2,
            "title": "Поиск конфликтов",
            "skill_name": "conflict_scan",
            "inputs": {},
            "depends_on": [1],
            "status": "created",
        },
        {
            "id": "step-3",
            "step_index": 3,
            "title": "Сформировать отчёт",
            "skill_name": "report",
            "inputs": {},
            "depends_on": [2],
            "status": "created",
        },
        {
            "id": "step-4",
            "step_index": 4,
            "title": "Сохранить в памяти",
            "skill_name": "memory_save",
            "inputs": {},
            "depends_on": [3],
            "status": "created",
        },
    ]
    store.insert_plan_steps(run["id"], plan_steps)

    client.post(f"/api/v1/runs/{run['id']}/start", headers=headers)
    res = client.get(f"/api/v1/runs/{run['id']}/events?token={token}&once=1")
    assert res.status_code == 200
    assert res.headers.get("content-type", "").startswith("text/event-stream")
    assert "event:" in res.text

    status = wait_for_run_done(client, run["id"], headers, timeout=15.0)
    assert status in ("done", "failed")

    artifacts = client.get(f"/api/v1/runs/{run['id']}/artifacts", headers=headers).json()
    assert any(a["type"] == "report_md" for a in artifacts)


def test_conflict_scan_produces_conflicts():
    client = make_client()
    headers = bootstrap(client, token="test-token")

    project = client.post("/api/v1/projects", json={"name": "Конфликт", "tags": [], "settings": {}}, headers=headers).json()
    run = client.post(
        f"/api/v1/projects/{project['id']}/runs",
        json={"query_text": "конфликт", "mode": "research"},
        headers=headers,
    ).json()
    run = unwrap_run(run)

    # вставляем конфликтующие факты
    store.insert_facts(run["id"], [
        {"id": "f1", "key": "Цена", "value": "10", "confidence": 0.5, "source_ids": [], "created_at": "2024-01-01T00:00:00Z"},
        {"id": "f2", "key": "Цена", "value": "12", "confidence": 0.5, "source_ids": [], "created_at": "2024-01-01T00:00:00Z"},
    ])

    # запускаем конфликт-сканирование напрямую
    from skills.conflict_scan import skill as conflict_skill
    result = conflict_skill.run({}, type("ctx", (), {"run": run}))
    assert any(e.get("type") == "conflict" for e in result.events)


def test_approval_flow_shell_skill_with_retry():
    port = 43125
    os.environ["ASTRA_DESKTOP_BRIDGE_PORT"] = str(port)
    server = start_bridge_server(port)

    client = make_client()
    headers = bootstrap(client, token="test-token")

    project = client.post("/api/v1/projects", json={"name": "Подтверждение", "tags": [], "settings": {}}, headers=headers).json()
    run = client.post(
        f"/api/v1/projects/{project['id']}/runs",
        json={"query_text": "Выполни shell команду", "mode": "execute_confirm"},
        headers=headers,
    ).json()
    run = unwrap_run(run)

    # план с навыком shell
    plan_steps = [
        {
            "id": "step-shell",
            "step_index": 0,
            "title": "Команда оболочки",
            "skill_name": "shell",
            "inputs": {"command": "echo test"},
            "depends_on": [],
            "status": "created",
        }
    ]
    store.insert_plan_steps(run["id"], plan_steps)

    client.post(f"/api/v1/runs/{run['id']}/start", headers=headers)

    approval_id = wait_for_pending_approval(client, run["id"], headers)
    assert approval_id is not None
    client.post(f"/api/v1/approvals/{approval_id}/approve", headers=headers)

    status = wait_for_run_done(client, run["id"], headers, timeout=10.0)
    assert status in ("done", "failed")

    # повтор шага
    client.post(f"/api/v1/runs/{run['id']}/steps/{plan_steps[0]['id']}/retry", headers=headers)

    approval_id = wait_for_pending_approval(client, run["id"], headers)
    assert approval_id is not None
    client.post(f"/api/v1/approvals/{approval_id}/approve", headers=headers)

    status = wait_for_run_done(client, run["id"], headers, timeout=10.0)
    assert status in ("done", "failed")

    tasks = client.get(f"/api/v1/runs/{run['id']}/tasks", headers=headers).json()
    attempts = [t for t in tasks if t.get("plan_step_id") == "step-shell"]
    assert len(attempts) >= 2

    server.shutdown()

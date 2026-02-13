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
from jsonschema import RefResolver, validate

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from apps.api.main import create_app
from memory import store


def make_client() -> TestClient:
    temp_dir = Path(tempfile.mkdtemp())
    os.environ["ASTRA_DATA_DIR"] = str(temp_dir)
    store.reset_for_tests()
    return TestClient(create_app())


def bootstrap(client: TestClient, token: str = "test-token") -> dict:
    client.post("/api/v1/auth/bootstrap", json={"token": token})
    return {"Authorization": f"Bearer {token}"}


def unwrap_run(payload: dict) -> dict:
    return payload.get("run") or payload


def load_schema(schema_name: str):
    schema_path = ROOT / "schemas" / schema_name
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    schema["$id"] = schema_path.resolve().as_uri()
    resolver = RefResolver(schema["$id"], schema)
    return schema, resolver


def parse_sse_events(text: str) -> list[dict]:
    events: list[dict] = []
    for chunk in text.strip().split("\n\n"):
        for line in chunk.splitlines():
            if line.startswith("data: "):
                payload = line.replace("data: ", "", 1)
                try:
                    events.append(json.loads(payload))
                except json.JSONDecodeError:
                    continue
    return events


class BridgeHandler(BaseHTTPRequestHandler):
    def do_POST(self):
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length).decode("utf-8")
        if self.path == "/shell/execute":
            payload = json.loads(body)
            response = {"output": f"ok {payload.get('command')}"}
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
    server = HTTPServer(("127.0.0.1", port), BridgeHandler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server


def test_snapshot_contract():
    client = make_client()
    headers = bootstrap(client)

    project = client.post("/api/v1/projects", json={"name": "Contracts", "tags": [], "settings": {}}, headers=headers).json()
    run = client.post(
        f"/api/v1/projects/{project['id']}/runs",
        json={"query_text": "contract snapshot", "mode": "plan_only"},
        headers=headers,
    ).json()
    run = unwrap_run(run)

    client.post(f"/api/v1/runs/{run['id']}/plan", headers=headers)

    snapshot = client.get(f"/api/v1/runs/{run['id']}/snapshot", headers=headers).json()
    schema, resolver = load_schema("snapshot.schema.json")
    validate(instance=snapshot, schema=schema, resolver=resolver)

    assert snapshot["run"]["status"] in ("created", "running", "paused", "done", "failed", "canceled", "planning")
    assert "plan" in snapshot
    assert "tasks" in snapshot
    assert "approvals" in snapshot
    assert "last_events" in snapshot


def test_event_contract_from_sse():
    client = make_client()
    headers = bootstrap(client)

    project = client.post("/api/v1/projects", json={"name": "Events", "tags": [], "settings": {}}, headers=headers).json()
    run = client.post(
        f"/api/v1/projects/{project['id']}/runs",
        json={"query_text": "contract events", "mode": "plan_only"},
        headers=headers,
    ).json()
    run = unwrap_run(run)

    res = client.get(f"/api/v1/runs/{run['id']}/events?token=test-token&once=1")
    assert res.status_code == 200
    events = parse_sse_events(res.text)
    assert events, "SSE не вернул событий"

    schema, resolver = load_schema("event.schema.json")
    validate(instance=events[0], schema=schema, resolver=resolver)


def test_approval_resolved_event():
    port = 43126
    os.environ["ASTRA_DESKTOP_BRIDGE_PORT"] = str(port)
    server = start_bridge_server(port)

    client = make_client()
    headers = bootstrap(client, token="test-token")

    project = client.post("/api/v1/projects", json={"name": "Approvals", "tags": [], "settings": {}}, headers=headers).json()
    run = client.post(
        f"/api/v1/projects/{project['id']}/runs",
        json={"query_text": "Выполни shell команду", "mode": "execute_confirm"},
        headers=headers,
    ).json()
    run = unwrap_run(run)

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

    approval_id = None
    start = time.time()
    while time.time() - start < 5.0:
        approvals = client.get(f"/api/v1/runs/{run['id']}/approvals", headers=headers).json()
        pending = [a for a in approvals if a.get("status") == "pending"]
        if pending:
            approval_id = pending[0]["id"]
            break
        time.sleep(0.2)

    assert approval_id is not None
    client.post(f"/api/v1/approvals/{approval_id}/approve", headers=headers)

    time.sleep(0.5)
    events_res = client.get(f"/api/v1/runs/{run['id']}/events/download?token=test-token")
    assert events_res.status_code == 200

    events = [json.loads(line) for line in events_res.text.splitlines() if line.strip()]
    assert any(e.get("type") == "approval_requested" for e in events)
    resolved = [e for e in events if e.get("type") == "approval_resolved"]
    assert resolved
    assert resolved[-1].get("payload", {}).get("status") in ("approved", "rejected", "expired")

    server.shutdown()

from __future__ import annotations

import argparse
import json
import os
import secrets
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

try:
    import yaml
except Exception:  # pragma: no cover - fallback
    yaml = None


ROOT = Path(__file__).resolve().parents[1]


@dataclass
class ScenarioResult:
    id: str
    status: str
    reason: str
    artifacts_dir: Path
    details: dict[str, Any]


def _load_scenarios(path: Path) -> list[dict[str, Any]]:
    raw = path.read_text(encoding="utf-8")
    if yaml is None:
        raise RuntimeError("pyyaml is required to parse scenarios.yaml")
    data = yaml.safe_load(raw)
    if isinstance(data, dict) and "scenarios" in data:
        return data["scenarios"]
    if isinstance(data, list):
        return data
    raise ValueError("Invalid scenarios.yaml format")


def _get_api_base() -> str:
    port = os.getenv("ASTRA_API_PORT", "8055")
    base = os.getenv("ASTRA_API_BASE", f"http://127.0.0.1:{port}/api/v1")
    return base.rstrip("/")


def _load_token_file(path: Path) -> str | None:
    if not path.exists():
        return None
    value = path.read_text(encoding="utf-8").strip()
    return value or None


def _bootstrap(client: httpx.Client) -> str:
    token_file = ROOT / ".astra" / "qa.token"
    token_file.parent.mkdir(parents=True, exist_ok=True)

    token = os.getenv("ASTRA_SESSION_TOKEN")
    if not token:
        token = _load_token_file(ROOT / ".astra" / "doctor.token")
    if not token:
        token = _load_token_file(token_file)
    if not token:
        token = secrets.token_hex(16)

    res = client.post("/auth/bootstrap", json={"token": token})
    if res.status_code == 200:
        token_file.write_text(token, encoding="utf-8")
        return token
    if res.status_code == 409:
        raise RuntimeError("token already set; export ASTRA_SESSION_TOKEN or delete session token in DB")
    raise RuntimeError(f"bootstrap failed: {res.status_code} {res.text}")


def _auth_headers(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def _ensure_project(client: httpx.Client, headers: dict[str, str]) -> dict[str, Any]:
    resp = client.get("/projects", headers=headers)
    resp.raise_for_status()
    projects = resp.json()
    if projects:
        return projects[0]
    created = client.post(
        "/projects",
        headers=headers,
        json={"name": "QA", "tags": ["qa"], "settings": {}},
    )
    created.raise_for_status()
    return created.json()


def _poll_snapshot(client: httpx.Client, headers: dict[str, str], run_id: str, timeout_s: int = 20) -> dict[str, Any]:
    start = time.time()
    last_error = None
    while time.time() - start < timeout_s:
        try:
            resp = client.get(f"/runs/{run_id}/snapshot", headers=headers)
            resp.raise_for_status()
            return resp.json()
        except Exception as exc:
            last_error = exc
            time.sleep(0.5)
    raise RuntimeError(f"snapshot timeout: {last_error}")


def _wait_run_finish(client: httpx.Client, headers: dict[str, str], run_id: str, timeout_s: int = 60) -> dict[str, Any]:
    start = time.time()
    snapshot = _poll_snapshot(client, headers, run_id, timeout_s=10)
    while time.time() - start < timeout_s:
        status = snapshot.get("run", {}).get("status")
        if status in ("done", "failed", "canceled"):
            return snapshot
        time.sleep(1.0)
        snapshot = _poll_snapshot(client, headers, run_id, timeout_s=10)
    return snapshot


def _extract_event_types(events: list[dict[str, Any]]) -> set[str]:
    return {event.get("type") for event in events if isinstance(event, dict)}


def _extract_llm_route_events(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    routes: list[dict[str, Any]] = []
    for event in events:
        if not isinstance(event, dict):
            continue
        if event.get("type") != "llm_route_decided":
            continue
        payload = event.get("payload")
        if isinstance(payload, dict):
            routes.append(payload)
    return routes


def _check_policy_routes(routes: list[dict[str, Any]]) -> tuple[bool, str]:
    for payload in routes:
        route = str(payload.get("route", "")).upper()
        summary = payload.get("items_summary_by_source_type") or {}
        if not isinstance(summary, dict):
            summary = {}
        telegram_count = summary.get("telegram_text") or 0
        screenshot_count = summary.get("screenshot_text") or 0
        if telegram_count and route != "LOCAL":
            return False, "policy_telegram_cloud"
        if screenshot_count and route != "LOCAL":
            return False, "policy_screenshot_cloud"
    return True, "ok"


def _collect_plan_kinds(plan: list[dict[str, Any]]) -> set[str]:
    return {step.get("kind") for step in plan if isinstance(step, dict)}


def _collect_danger_flags(plan: list[dict[str, Any]]) -> set[str]:
    flags: set[str] = set()
    for step in plan:
        if isinstance(step, dict):
            for flag in step.get("danger_flags") or []:
                flags.add(str(flag))
    return flags


def _check_invariants(
    scenario: dict[str, Any],
    response: dict[str, Any] | None,
    snapshot: dict[str, Any] | None,
    executed: bool,
) -> tuple[bool, str, dict[str, Any]]:
    expect = scenario.get("expect") or {}
    details: dict[str, Any] = {}

    if not response:
        return False, "no_response", details

    kind = response.get("kind")
    intent = None
    intent_payload = response.get("intent") or {}
    if isinstance(intent_payload, dict):
        intent = intent_payload.get("intent")
    details["intent"] = intent
    expected_intent = expect.get("intent")
    if expected_intent and intent != expected_intent:
        return False, f"intent_mismatch expected {expected_intent} got {intent}", details

    if expected_intent == "CHAT" and kind != "chat":
        return False, f"expected chat response, got {kind}", details

    run = snapshot.get("run") if snapshot else None
    if run is None:
        return False, "no_run_snapshot", details

    details["run_id"] = run.get("id")
    details["run_status"] = run.get("status")
    details["executed"] = executed

    if run.get("status") not in ("created", "running", "paused", "done", "failed", "canceled"):
        return False, f"unknown_run_status {run.get('status')}", details

    plan = snapshot.get("plan") or []
    if expect.get("plan") and not plan:
        return False, "plan_missing", details

    plan_kinds = _collect_plan_kinds(plan)
    details["plan_kinds"] = sorted(k for k in plan_kinds if k)
    expected_kinds = expect.get("step_kinds") or []
    for kind_needed in expected_kinds:
        if kind_needed not in plan_kinds:
            return False, f"missing_step_kind {kind_needed}", details

    if expect.get("requires_approval"):
        has_approval = any(step.get("requires_approval") for step in plan if isinstance(step, dict))
        if not has_approval:
            return False, "requires_approval_missing", details

    expected_flags = set(expect.get("danger_flags") or [])
    if expected_flags:
        actual_flags = _collect_danger_flags(plan)
        details["danger_flags"] = sorted(actual_flags)
        if not expected_flags.issubset(actual_flags):
            return False, f"danger_flags_missing {expected_flags - actual_flags}", details

    events = snapshot.get("last_events") or []
    event_types = _extract_event_types(events)
    details["event_types"] = sorted(event_types)

    if "intent_decided" not in event_types:
        return False, "intent_decided_missing", details

    if expect.get("plan") and "plan_created" not in event_types:
        return False, "plan_created_missing", details

    if expect.get("memory_saved") and "memory_saved" not in event_types:
        return False, "memory_saved_missing", details

    if expect.get("no_memory"):
        if "memory_saved" in event_types or "MEMORY_COMMIT" in plan_kinds:
            return False, "unexpected_memory_saved", details

    if expect.get("reminder_created"):
        if "reminder_created" not in event_types:
            return False, "reminder_created_missing", details

    if expect.get("requires_approval") and executed:
        if "approval_requested" not in event_types and "step_paused_for_approval" not in event_types:
            return False, "approval_not_requested", details

    llm_routes = _extract_llm_route_events(events)
    details["llm_routes"] = [
        {"route": r.get("route"), "reason": r.get("reason"), "provider": r.get("provider")} for r in llm_routes
    ]
    policy_ok, policy_reason = _check_policy_routes(llm_routes)
    if not policy_ok:
        return False, policy_reason, details

    expected_route = expect.get("llm_route")
    if expected_route:
        if not llm_routes:
            return False, "llm_route_missing", details
        expected_route = str(expected_route).upper()
        if all(str(r.get("route", "")).upper() != expected_route for r in llm_routes):
            return False, f"llm_route_mismatch expected {expected_route}", details

    return True, "ok", details


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=["dry-run", "safe-run"], default="dry-run")
    parser.add_argument("--scenarios", default=str(ROOT / "scripts" / "scenarios.yaml"))
    parser.add_argument("--timeout", type=int, default=90)
    args = parser.parse_args()

    api_base = _get_api_base()
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    artifacts_root = ROOT / "artifacts" / "qa" / timestamp
    artifacts_root.mkdir(parents=True, exist_ok=True)

    try:
        scenarios = _load_scenarios(Path(args.scenarios))
    except Exception as exc:
        print(f"Failed to load scenarios: {exc}")
        return 1

    results: list[ScenarioResult] = []

    with httpx.Client(base_url=api_base, timeout=15.0) as client:
        try:
            token = _bootstrap(client)
        except Exception as exc:
            reason = f"api_unreachable: {exc}"
            for scenario in scenarios:
                scenario_id = scenario.get("id") or "unknown"
                scenario_dir = artifacts_root / scenario_id
                scenario_dir.mkdir(parents=True, exist_ok=True)
                summary_path = scenario_dir / "summary.txt"
                summary_path.write_text(reason, encoding="utf-8")
                results.append(ScenarioResult(scenario_id, "FAIL", reason, scenario_dir, {}))
            _write_report(artifacts_root, results)
            return 1

        headers = _auth_headers(token)
        project = _ensure_project(client, headers)
        project_id = project.get("id")

        for scenario in scenarios:
            scenario_id = scenario.get("id") or "unknown"
            scenario_dir = artifacts_root / scenario_id
            scenario_dir.mkdir(parents=True, exist_ok=True)
            response_json: dict[str, Any] | None = None
            snapshot: dict[str, Any] | None = None

            executed = False
            try:
                should_execute = bool(scenario.get("execute"))
                if args.mode == "safe-run" and scenario.get("safe_run"):
                    should_execute = True
                run_mode = "execute_confirm" if should_execute else "plan_only"

                create_resp = client.post(
                    f"/projects/{project_id}/runs",
                    headers=headers,
                    json={"query_text": scenario.get("text"), "mode": run_mode},
                )
                create_resp.raise_for_status()
                response_json = create_resp.json()

                run = response_json.get("run")
                run_id = run.get("id") if isinstance(run, dict) else None
                if run_id:
                    snapshot = _poll_snapshot(client, headers, run_id, timeout_s=20)

                    if should_execute:
                        executed = True
                        client.post(f"/runs/{run_id}/start", headers=headers)
                        snapshot = _wait_run_finish(client, headers, run_id, timeout_s=args.timeout)

            except Exception as exc:
                reason = f"request_failed: {exc}"
                summary_path = scenario_dir / "summary.txt"
                summary_path.write_text(reason, encoding="utf-8")
                results.append(ScenarioResult(scenario_id, "FAIL", reason, scenario_dir, {}))
                continue

            if response_json is not None:
                (scenario_dir / "response.json").write_text(json.dumps(response_json, ensure_ascii=False, indent=2), encoding="utf-8")
            if snapshot is not None:
                (scenario_dir / "snapshot.json").write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")
                (scenario_dir / "events.json").write_text(json.dumps(snapshot.get("last_events") or [], ensure_ascii=False, indent=2), encoding="utf-8")

            ok, reason, details = _check_invariants(scenario, response_json, snapshot, executed)
            summary = {
                "id": scenario_id,
                "status": "PASS" if ok else "FAIL",
                "reason": reason,
                "details": details,
            }
            (scenario_dir / "summary.txt").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
            results.append(ScenarioResult(scenario_id, summary["status"], reason, scenario_dir, details))

    _write_report(artifacts_root, results)
    return 0


def _write_report(artifacts_root: Path, results: list[ScenarioResult]) -> None:
    report_path = artifacts_root / "report.md"
    lines = ["# QA Report", "", "| Scenario | Status | Reason | Artifacts |", "| --- | --- | --- | --- |"]
    for result in results:
        rel_path = result.artifacts_dir.relative_to(ROOT)
        lines.append(f"| {result.id} | {result.status} | {result.reason} | {rel_path} |")

    fail_reasons: dict[str, int] = {}
    for result in results:
        if result.status == "FAIL":
            fail_reasons[result.reason] = fail_reasons.get(result.reason, 0) + 1

    if fail_reasons:
        lines.append("")
        lines.append("## Частые причины падений")
        for reason, count in sorted(fail_reasons.items(), key=lambda item: item[1], reverse=True):
            lines.append(f"- {reason}: {count}")

    report_path.write_text("\n".join(lines), encoding="utf-8")

    latest_path = ROOT / "artifacts" / "qa" / "latest_report.md"
    latest_path.parent.mkdir(parents=True, exist_ok=True)
    latest_path.write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    sys.exit(main())

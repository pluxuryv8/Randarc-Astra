from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from typing import Any, Iterable
from urllib.parse import urlparse

from core.event_bus import emit
from core.safety.approvals import (
    build_cloud_financial_preview,
    preview_summary,
    proposed_actions_from_preview,
)
from memory import store

SOURCE_TYPES = {
    "user_prompt",
    "web_page_text",
    "telegram_text",
    "file_content",
    "app_ui_text",
    "screenshot_text",
    "system_note",
    "internal_summary",
}

SENSITIVITIES = {
    "public",
    "personal",
    "financial",
    "confidential",
}

ROUTE_LOCAL = "LOCAL"
ROUTE_CLOUD = "CLOUD"
FINANCIAL_APPROVAL_SCOPE = "cloud_financial_file"


@dataclass
class ContextItem:
    content: Any
    source_type: str
    sensitivity: str
    provenance: str | None = None

    def __post_init__(self) -> None:
        if self.source_type not in SOURCE_TYPES:
            raise ValueError(f"Unsupported source_type: {self.source_type}")
        if self.sensitivity not in SENSITIVITIES:
            raise ValueError(f"Unsupported sensitivity: {self.sensitivity}")


@dataclass
class PolicyFlags:
    auto_cloud_enabled: bool = True
    cloud_allowed: bool = True
    strict_local: bool = False
    max_cloud_chars: int = 8000
    max_cloud_item_chars: int = 2000

    @classmethod
    def from_settings(cls, settings: dict | None) -> "PolicyFlags":
        cfg = (settings or {}).get("privacy") or (settings or {}).get("routing") or {}
        return cls(
            auto_cloud_enabled=bool(cfg.get("auto_cloud_enabled", True)),
            cloud_allowed=bool(cfg.get("cloud_allowed", True)),
            strict_local=bool(cfg.get("strict_local", False)),
            max_cloud_chars=int(cfg.get("max_cloud_chars", 8000)),
            max_cloud_item_chars=int(cfg.get("max_cloud_item_chars", 2000)),
        )


@dataclass
class RoutingDecision:
    route: str
    reason: str
    required_approval: str | None
    redaction_plan: dict[str, Any]


@dataclass
class SanitizationResult:
    items: list[ContextItem]
    removed_counts_by_source: dict[str, int]
    redacted_count: int
    total_chars: int
    truncated: bool


_SECRET_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"(?i)(api[_-]?key|token|secret|password|passphrase)\s*[:=]\s*([^\s\"']+)") ,
    re.compile(r"(?i)bearer\s+[A-Za-z0-9\-\._~\+\/]+=*"),
    re.compile(r"sk-[A-Za-z0-9]{10,}"),
]


def _redact_secrets(text: str) -> tuple[str, int]:
    total = 0
    value = text
    for pattern in _SECRET_PATTERNS:
        value, count = pattern.subn("[REDACTED]", value)
        total += count
    return value, total


def _estimate_length(value: Any) -> int:
    if isinstance(value, str):
        return len(value)
    if isinstance(value, dict):
        total = 0
        for item in value.values():
            total += _estimate_length(item)
        return total
    if isinstance(value, list):
        return sum(_estimate_length(item) for item in value)
    return len(str(value))


def _truncate_string(value: str, max_chars: int) -> str:
    if max_chars <= 0:
        return ""
    if len(value) <= max_chars:
        return value
    return value[:max_chars]


def _truncate_content(value: Any, max_chars: int) -> Any:
    if max_chars <= 0:
        return ""
    if isinstance(value, str):
        return _truncate_string(value, max_chars)
    if isinstance(value, dict):
        if "snippet" in value and isinstance(value["snippet"], str):
            truncated = dict(value)
            truncated["snippet"] = _truncate_string(value["snippet"], max_chars)
            return truncated
        return value
    if isinstance(value, list):
        if all(isinstance(item, str) for item in value):
            joined = "\n".join(value)
            truncated = _truncate_string(joined, max_chars)
            return truncated.split("\n") if truncated else []
        return value
    return value


def _sanitize_value(value: Any, max_chars: int) -> tuple[Any, int, bool]:
    if isinstance(value, str):
        redacted, count = _redact_secrets(value)
        truncated = len(redacted) > max_chars
        return _truncate_string(redacted, max_chars), count, truncated
    if isinstance(value, dict):
        redacted_total = 0
        truncated_any = False
        sanitized: dict[str, Any] = {}
        for key, item in value.items():
            if isinstance(item, str):
                redacted, count = _redact_secrets(item)
                redacted_total += count
                truncated_any = truncated_any or len(redacted) > max_chars
                sanitized[key] = _truncate_string(redacted, max_chars)
            else:
                sanitized[key] = item
        return sanitized, redacted_total, truncated_any
    if isinstance(value, list):
        redacted_total = 0
        truncated_any = False
        sanitized_list = []
        for item in value:
            if isinstance(item, str):
                redacted, count = _redact_secrets(item)
                redacted_total += count
                truncated_any = truncated_any or len(redacted) > max_chars
                sanitized_list.append(_truncate_string(redacted, max_chars))
            else:
                sanitized_list.append(item)
        return sanitized_list, redacted_total, truncated_any
    return value, 0, False


def sanitize_context_items(items: list[ContextItem], allow_financial_file: bool, flags: PolicyFlags) -> SanitizationResult:
    removed_counts: dict[str, int] = {key: 0 for key in SOURCE_TYPES}
    sanitized_items: list[ContextItem] = []
    redacted_total = 0
    total_chars = 0
    truncated_any = False

    for item in items:
        if item.source_type == "telegram_text":
            removed_counts[item.source_type] += 1
            continue
        if item.source_type == "screenshot_text":
            removed_counts[item.source_type] += 1
            continue
        if item.source_type == "file_content" and item.sensitivity == "financial" and not allow_financial_file:
            removed_counts[item.source_type] += 1
            continue

        sanitized_content, redacted_count, truncated = _sanitize_value(item.content, flags.max_cloud_item_chars)
        redacted_total += redacted_count
        truncated_any = truncated_any or truncated

        item_len = _estimate_length(sanitized_content)
        if total_chars + item_len > flags.max_cloud_chars:
            remaining = flags.max_cloud_chars - total_chars
            sanitized_content = _truncate_content(sanitized_content, remaining)
            item_len = _estimate_length(sanitized_content)
            truncated_any = True

        if item_len <= 0:
            removed_counts[item.source_type] += 1
            continue

        total_chars += item_len
        sanitized_items.append(
            ContextItem(
                content=sanitized_content,
                source_type=item.source_type,
                sensitivity=item.sensitivity,
                provenance=item.provenance,
            )
        )

        if total_chars >= flags.max_cloud_chars:
            break

    return SanitizationResult(
        items=sanitized_items,
        removed_counts_by_source=removed_counts,
        redacted_count=redacted_total,
        total_chars=total_chars,
        truncated=truncated_any,
    )


def summarize_items(items: Iterable[ContextItem]) -> dict[str, Any]:
    counts_by_source: dict[str, int] = {key: 0 for key in SOURCE_TYPES}
    counts_by_sensitivity: dict[str, int] = {key: 0 for key in SENSITIVITIES}
    for item in items:
        counts_by_source[item.source_type] = counts_by_source.get(item.source_type, 0) + 1
        counts_by_sensitivity[item.sensitivity] = counts_by_sensitivity.get(item.sensitivity, 0) + 1
    return {
        "by_source_type": counts_by_source,
        "by_sensitivity": counts_by_sensitivity,
    }


def decide_route(intent: str | None, items: list[ContextItem], flags: PolicyFlags, approved_scopes: set[str] | None = None) -> RoutingDecision:
    approved_scopes = approved_scopes or set()
    if flags.strict_local:
        return RoutingDecision(route=ROUTE_LOCAL, reason="strict_local", required_approval=None, redaction_plan={})

    has_telegram = any(item.source_type == "telegram_text" for item in items)
    if has_telegram:
        return RoutingDecision(route=ROUTE_LOCAL, reason="telegram_text_present", required_approval=None, redaction_plan={"drop": ["telegram_text"]})

    has_screenshot_text = any(item.source_type == "screenshot_text" for item in items)
    if has_screenshot_text:
        return RoutingDecision(route=ROUTE_LOCAL, reason="screenshot_text_present", required_approval=None, redaction_plan={"drop": ["screenshot_text"]})

    has_financial_file = any(item.source_type == "file_content" and item.sensitivity == "financial" for item in items)
    if has_financial_file and FINANCIAL_APPROVAL_SCOPE not in approved_scopes:
        return RoutingDecision(
            route=ROUTE_LOCAL,
            reason="financial_file_requires_approval",
            required_approval=FINANCIAL_APPROVAL_SCOPE,
            redaction_plan={"drop": ["file_content"]},
        )
    if has_financial_file and FINANCIAL_APPROVAL_SCOPE in approved_scopes and flags.auto_cloud_enabled and flags.cloud_allowed:
        return RoutingDecision(route=ROUTE_CLOUD, reason="financial_file_approved", required_approval=None, redaction_plan={})

    has_web_text = any(item.source_type == "web_page_text" for item in items)
    if has_web_text and flags.auto_cloud_enabled and flags.cloud_allowed:
        return RoutingDecision(route=ROUTE_CLOUD, reason="web_page_text", required_approval=None, redaction_plan={})

    has_heavy_public_text = False
    for item in items:
        if item.source_type in ("user_prompt", "system_note", "internal_summary") and item.sensitivity == "public":
            if _estimate_length(item.content) >= 1200:
                has_heavy_public_text = True
                break
    if has_heavy_public_text and flags.auto_cloud_enabled and flags.cloud_allowed:
        return RoutingDecision(route=ROUTE_CLOUD, reason="heavy_public_text", required_approval=None, redaction_plan={})

    return RoutingDecision(route=ROUTE_LOCAL, reason="default_local", required_approval=None, redaction_plan={})


def _is_local_endpoint(url: str | None) -> bool:
    if not url:
        return False
    parsed = urlparse(url)
    host = parsed.hostname
    if not host:
        return False
    return host in {"localhost", "127.0.0.1", "::1", "0.0.0.0"}


def resolve_llm_settings(settings: dict, route: str) -> dict:
    if route == ROUTE_LOCAL:
        llm_local = settings.get("llm_local") or settings.get("llm") or {}
        provider = llm_local.get("provider")
        endpoint = llm_local.get("base_url") or llm_local.get("endpoint")
        if provider != "openai" or not _is_local_endpoint(endpoint):
            raise RuntimeError("Local LLM is not configured")
        return llm_local

    llm_cloud = settings.get("llm_cloud") or settings.get("llm") or {}
    if not llm_cloud.get("provider"):
        raise RuntimeError("Cloud LLM is not configured")
    return llm_cloud


def _wait_for_approval(approval_id: str, run_id: str) -> dict | None:
    while True:
        approval = store.get_approval(approval_id)
        if not approval:
            return None
        if approval["status"] in ("approved", "rejected", "expired"):
            return approval
        run = store.get_run(run_id)
        if run and run["status"] == "canceled":
            approval = store.update_approval_status(approval_id, "expired", "system")
            return approval
        time.sleep(0.5)


def _build_approval_preview(items: list[ContextItem], max_chars: int = 400) -> str:
    parts = []
    for item in items:
        label = item.provenance or item.source_type
        if isinstance(item.content, str):
            snippet = _truncate_string(item.content, max_chars)
        else:
            snippet = _truncate_string(json.dumps(item.content, ensure_ascii=False), max_chars)
        parts.append(f"- {label}: {snippet}")
    return "\n".join(parts)


def request_cloud_approval(ctx, decision: RoutingDecision, items: list[ContextItem]) -> bool:
    if not decision.required_approval:
        return False

    flags = PolicyFlags.from_settings(ctx.settings if ctx else {})
    redaction = sanitize_context_items(items, allow_financial_file=True, flags=flags)
    preview = build_cloud_financial_preview(
        [
            {"source_type": item.source_type, "provenance": item.provenance}
            for item in items
            if item.source_type == "file_content"
        ],
        redaction_summary=redaction.removed_counts_by_source,
    )
    title = "Подтверждение отправки финансовых данных"
    description = preview.get("risk") or "Approval required to send financial file content to cloud."

    approval = store.create_approval(
        run_id=ctx.run["id"],
        task_id=ctx.task["id"],
        step_id=ctx.plan_step.get("id") if ctx and ctx.plan_step else None,
        scope=decision.required_approval,
        approval_type="CLOUD_FINANCIAL",
        title=title,
        description=description,
        proposed_actions=proposed_actions_from_preview("CLOUD_FINANCIAL", preview),
        preview=preview,
    )
    emit(
        ctx.run["id"],
        "approval_requested",
        "Approval requested",
        {
            "approval_id": approval["id"],
            "approval_type": approval.get("approval_type"),
            "step_id": approval.get("step_id"),
            "preview_summary": preview_summary(preview),
            "scope": approval["scope"],
            "title": approval["title"],
            "description": approval["description"],
        },
        task_id=ctx.task["id"],
        step_id=ctx.plan_step["id"],
    )

    store.update_task_status(ctx.task["id"], "waiting_approval")
    emit(
        ctx.run["id"],
        "task_progress",
        "Waiting for approval",
        {
            "task_id": ctx.task["id"],
            "step_id": ctx.plan_step["id"],
            "progress": {"current": 0, "total": 1, "unit": "approval"},
            "last_message": "Waiting for approval",
        },
        task_id=ctx.task["id"],
        step_id=ctx.plan_step["id"],
    )

    approval = _wait_for_approval(approval["id"], ctx.run["id"])
    if approval:
        emit(
            ctx.run["id"],
            "approval_resolved",
            "Approval resolved",
            {
                "approval_id": approval["id"],
                "status": approval.get("status"),
                "decision": approval.get("decision"),
                "approval_type": approval.get("approval_type"),
                "step_id": approval.get("step_id"),
            },
            task_id=ctx.task["id"],
            step_id=ctx.plan_step["id"],
        )

    if approval and approval.get("status") == "approved":
        emit(
            ctx.run["id"],
            "approval_approved",
            "Approval approved",
            {"approval_id": approval["id"]},
            task_id=ctx.task["id"],
            step_id=ctx.plan_step["id"],
        )
        store.update_task_status(ctx.task["id"], "running")
        return True

    emit(
        ctx.run["id"],
        "approval_rejected",
        "Approval rejected",
        {"approval_id": approval["id"] if approval else None},
        task_id=ctx.task["id"],
        step_id=ctx.plan_step["id"],
    )
    store.update_task_status(ctx.task["id"], "running")
    return False

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from core.llm_routing import ContextItem


@dataclass
class LLMRequest:
    purpose: str
    task_kind: str | None = None
    context_items: list[ContextItem] = field(default_factory=list)
    messages: list[dict[str, Any]] | None = None
    render_messages: Callable[[list[ContextItem]], list[dict[str, Any]]] | None = None
    preferred_model_kind: str = "chat"
    max_tokens: int | None = None
    temperature: float = 0.2
    top_p: float | None = None
    repeat_penalty: float | None = None
    json_schema: dict | None = None
    tools: list[dict] | None = None
    run_id: str | None = None
    task_id: str | None = None
    step_id: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class LLMResponse:
    text: str
    usage: dict | None
    provider: str
    model_id: str | None
    latency_ms: int
    cache_hit: bool
    route_reason: str
    status: str = "ok"
    error_type: str | None = None
    http_status: int | None = None
    retry_count: int = 0
    raw: dict | None = None

from __future__ import annotations

import hashlib
import json
import os
import random
import threading
import time
from collections import deque
from dataclasses import dataclass
from typing import Any, Iterable

from core.brain.providers import CloudLLMProvider, LocalLLMProvider, ProviderError
from core.brain.types import LLMRequest, LLMResponse
from core.event_bus import emit
from core.llm_routing import (
    ROUTE_CLOUD,
    ROUTE_LOCAL,
    ContextItem,
    PolicyFlags,
    decide_route,
    request_cloud_approval,
    sanitize_context_items,
)
from core.secrets import get_secret


@dataclass
class BrainConfig:
    local_base_url: str
    local_chat_model: str
    local_code_model: str
    local_timeout_s: int
    cloud_base_url: str
    cloud_model: str
    cloud_enabled: bool
    auto_cloud_enabled: bool
    max_concurrency: int
    max_retries: int
    backoff_base_ms: int
    budget_per_run: int | None
    budget_per_step: int | None

    @classmethod
    def from_env(cls) -> "BrainConfig":
        def _env_bool(name: str, default: bool) -> bool:
            raw = os.getenv(name)
            if raw is None:
                return default
            return raw.strip().lower() in {"1", "true", "yes", "on"}

        def _env_int(name: str, default: int | None) -> int | None:
            raw = os.getenv(name)
            if raw is None:
                return default
            try:
                return int(raw)
            except ValueError:
                return default

        api_key = os.getenv("OPENAI_API_KEY") or get_secret("OPENAI_API_KEY")
        cloud_enabled = _env_bool("ASTRA_CLOUD_ENABLED", False)
        if not api_key:
            cloud_enabled = False

        return cls(
            local_base_url=os.getenv("ASTRA_LLM_LOCAL_BASE_URL", "http://127.0.0.1:11434"),
            local_chat_model=os.getenv("ASTRA_LLM_LOCAL_CHAT_MODEL", "saiga-nemo-12b"),
            local_code_model=os.getenv("ASTRA_LLM_LOCAL_CODE_MODEL", "deepseek-coder-v2:16b-lite-instruct-q8_0"),
            local_timeout_s=max(1, _env_int("ASTRA_LLM_LOCAL_TIMEOUT_S", 30) or 30),
            cloud_base_url=os.getenv("ASTRA_LLM_CLOUD_BASE_URL", "https://api.openai.com/v1"),
            cloud_model=os.getenv("ASTRA_LLM_CLOUD_MODEL", "gpt-4.1"),
            cloud_enabled=cloud_enabled,
            auto_cloud_enabled=_env_bool("ASTRA_AUTO_CLOUD_ENABLED", False),
            max_concurrency=_env_int("ASTRA_LLM_MAX_CONCURRENCY", 1) or 1,
            max_retries=_env_int("ASTRA_LLM_MAX_RETRIES", 3) or 0,
            backoff_base_ms=_env_int("ASTRA_LLM_BACKOFF_BASE_MS", 350) or 350,
            budget_per_run=_env_int("ASTRA_LLM_BUDGET_PER_RUN", None),
            budget_per_step=_env_int("ASTRA_LLM_BUDGET_PER_STEP", None),
        )


class BrainQueue:
    def __init__(self, max_concurrency: int) -> None:
        self.max_concurrency = max(1, int(max_concurrency))
        self._lock = threading.Lock()
        self._condition = threading.Condition(self._lock)
        self._queue: deque[object] = deque()
        self._inflight = 0

    def acquire(self):
        token = object()
        with self._condition:
            self._queue.append(token)
            while self._queue[0] is not token or self._inflight >= self.max_concurrency:
                self._condition.wait()
            self._queue.popleft()
            self._inflight += 1
        return token

    def release(self, token: object) -> None:
        with self._condition:
            self._inflight = max(0, self._inflight - 1)
            self._condition.notify_all()


class BrainRouter:
    def __init__(self, config: BrainConfig | None = None) -> None:
        self.config = config or BrainConfig.from_env()
        self.queue = BrainQueue(self.config.max_concurrency)
        self._cache: dict[str, dict[str, LLMResponse]] = {}
        self._run_counts: dict[str, int] = {}
        self._step_counts: dict[tuple[str, str], int] = {}
        self._local_failures: dict[tuple[str, str], int] = {}

    def call(self, request: LLMRequest, ctx=None) -> LLMResponse:
        run_id = request.run_id or (ctx.run.get("id") if ctx else None)
        task_id = request.task_id or (ctx.task.get("id") if ctx else None)
        step_id = request.step_id or (ctx.plan_step.get("id") if ctx else None)

        if self._is_qa_mode(ctx):
            model_id = "qa_stub"
            self._emit(
                run_id,
                "llm_route_decided",
                "LLM route decided",
                {
                    "route": ROUTE_LOCAL,
                    "reason": "qa_mode",
                    "provider": "local",
                    "model_id": model_id,
                    "items_summary_by_source_type": self._items_summary_by_source(request.context_items or []),
                },
                task_id=task_id,
                step_id=step_id,
            )
            self._emit(
                run_id,
                "llm_request_started",
                "LLM request started",
                {"provider": "local", "model_id": model_id},
                task_id=task_id,
                step_id=step_id,
            )
            response = LLMResponse(
                text=self._qa_response(request),
                usage=None,
                provider="local",
                model_id=model_id,
                latency_ms=0,
                cache_hit=True,
                route_reason="qa_mode",
            )
            self._emit(
                run_id,
                "llm_request_succeeded",
                "LLM request succeeded",
                {
                    "provider": response.provider,
                    "model_id": response.model_id,
                    "latency_ms": response.latency_ms,
                    "usage_if_available": response.usage,
                    "cache_hit": True,
                },
                task_id=task_id,
                step_id=step_id,
            )
            return response

        policy_flags = PolicyFlags.from_settings(ctx.settings if ctx else {})
        if os.getenv("ASTRA_CLOUD_ENABLED") is not None:
            policy_flags.cloud_allowed = self.config.cloud_enabled
        if os.getenv("ASTRA_AUTO_CLOUD_ENABLED") is not None:
            policy_flags.auto_cloud_enabled = self.config.auto_cloud_enabled

        context_items = request.context_items or []
        decision = decide_route(request.purpose, context_items, policy_flags)

        route = decision.route
        route_reason = decision.reason
        heuristic_reason = self._auto_switch_reason(request, context_items, run_id, policy_flags)

        if heuristic_reason and policy_flags.auto_cloud_enabled and policy_flags.cloud_allowed:
            if decision.reason not in ("telegram_text_present", "strict_local"):
                route = ROUTE_CLOUD
                route_reason = heuristic_reason

        approved_for_cloud = False
        if decision.required_approval and route == ROUTE_CLOUD and policy_flags.auto_cloud_enabled and policy_flags.cloud_allowed:
            approved_for_cloud = request_cloud_approval(ctx, decision, context_items)
            if approved_for_cloud:
                route = ROUTE_CLOUD
                route_reason = "financial_file_approved"
            else:
                route = ROUTE_LOCAL
                route_reason = "financial_file_not_approved"
        elif decision.required_approval and route == ROUTE_CLOUD:
            route = ROUTE_LOCAL
            route_reason = "cloud_disabled"

        if decision.reason in ("telegram_text_present", "strict_local"):
            route = ROUTE_LOCAL
            route_reason = decision.reason

        provider_name = "local" if route == ROUTE_LOCAL else "cloud"
        model_id = self._select_model(route, request.preferred_model_kind, ctx)

        sanitize_result = None
        final_items = context_items
        original_len = self._items_length(context_items)

        if route == ROUTE_CLOUD:
            sanitize_result = sanitize_context_items(context_items, approved_for_cloud, policy_flags)
            final_items = sanitize_result.items
            final_len = sanitize_result.total_chars
            truncated_chars = max(0, original_len - final_len)
            self._emit(
                run_id,
                "llm_request_sanitized",
                "LLM request sanitized",
                {
                    "removed_counts_by_source_type": sanitize_result.removed_counts_by_source,
                    "truncated_chars": truncated_chars,
                    "final_len": final_len,
                },
                task_id=task_id,
                step_id=step_id,
            )
            if final_len <= 0:
                route = ROUTE_LOCAL
                route_reason = "sanitized_empty_fallback"
                provider_name = "local"
                model_id = self._select_model(route, request.preferred_model_kind, ctx)

        items_summary = self._items_summary_by_source(context_items)
        self._emit(
            run_id,
            "llm_route_decided",
            "LLM route decided",
            {
                "route": route,
                "reason": route_reason,
                "provider": provider_name,
                "model_id": model_id,
                "items_summary_by_source_type": items_summary,
            },
            task_id=task_id,
            step_id=step_id,
        )

        messages = self._build_messages(request, final_items)
        cache_key = self._cache_key(route, model_id, request, messages)
        cached = self._cache_get(run_id, cache_key)
        if cached:
            self._emit(
                run_id,
                "llm_request_started",
                "LLM request started",
                {"provider": cached.provider, "model_id": cached.model_id},
                task_id=task_id,
                step_id=step_id,
            )
            self._emit(
                run_id,
                "llm_request_succeeded",
                "LLM request succeeded",
                {
                    "provider": cached.provider,
                    "model_id": cached.model_id,
                    "latency_ms": 0,
                    "usage_if_available": cached.usage,
                    "cache_hit": True,
                },
                task_id=task_id,
                step_id=step_id,
            )
            return cached

        if run_id:
            budget = self._check_budget(run_id, step_id)
            if budget is not None:
                budget_name, limit, current = budget
                self._emit(
                    run_id,
                    "llm_budget_exceeded",
                    "LLM budget exceeded",
                    {
                        "budget_name": budget_name,
                        "limit": limit,
                        "current": current,
                    },
                    task_id=task_id,
                    step_id=step_id,
                )
                return LLMResponse(
                    text="",
                    usage=None,
                    provider=provider_name,
                    model_id=model_id,
                    latency_ms=0,
                    cache_hit=False,
                    route_reason=route_reason,
                    status="budget_exceeded",
                    error_type="budget_exceeded",
                )

        token = self.queue.acquire()
        start = time.time()
        try:
            self._emit(
                run_id,
                "llm_request_started",
                "LLM request started",
                {"provider": provider_name, "model_id": model_id},
                task_id=task_id,
                step_id=step_id,
            )

            if route == ROUTE_LOCAL:
                result = self._call_local(messages, request, model_id)
                response = LLMResponse(
                    text=result.text,
                    usage=result.usage,
                    provider="local",
                    model_id=model_id,
                    latency_ms=int((time.time() - start) * 1000),
                    cache_hit=False,
                    route_reason=route_reason,
                    raw=result.raw,
                )
                self._note_local_result(run_id, request.preferred_model_kind, response)
            else:
                response = self._call_cloud_with_retry(messages, request, model_id, start)
                response.route_reason = route_reason

            self._emit(
                run_id,
                "llm_request_succeeded",
                "LLM request succeeded",
                {
                    "provider": response.provider,
                    "model_id": response.model_id,
                    "latency_ms": response.latency_ms,
                    "usage_if_available": response.usage,
                    "cache_hit": response.cache_hit,
                },
                task_id=task_id,
                step_id=step_id,
            )

            self._cache_set(run_id, cache_key, response)
            self._increment_budget(run_id, step_id)
            return response
        except ProviderError as exc:
            self._emit(
                run_id,
                "llm_request_failed",
                "LLM request failed",
                {
                    "provider": exc.provider,
                    "model_id": model_id,
                    "error_type": exc.error_type,
                    "http_status_if_any": exc.status_code,
                    "retry_count": getattr(exc, "retry_count", 0),
                },
                task_id=task_id,
                step_id=step_id,
            )
            if exc.provider == "local" and exc.artifact_path:
                self._emit(
                    run_id,
                    "local_llm_http_error",
                    "Local LLM HTTP error",
                    {
                        "status": exc.status_code,
                        "model_id": model_id,
                        "artifact_path": exc.artifact_path,
                    },
                    task_id=task_id,
                    step_id=step_id,
                )
            if route == ROUTE_LOCAL:
                self._note_local_failure(run_id, request.preferred_model_kind)
            raise
        finally:
            self.queue.release(token)

    def _call_local(self, messages: list[dict[str, Any]], request: LLMRequest, model_id: str) -> Any:
        provider = LocalLLMProvider(
            self.config.local_base_url,
            self.config.local_chat_model,
            self.config.local_code_model,
            timeout_s=self.config.local_timeout_s,
        )
        return provider.chat(
            messages,
            model_kind=request.preferred_model_kind,
            temperature=request.temperature,
            max_tokens=request.max_tokens,
            json_schema=request.json_schema,
            tools=request.tools,
            run_id=request.run_id,
            step_id=request.step_id,
            purpose=request.purpose,
        )

    def _call_cloud_with_retry(self, messages: list[dict[str, Any]], request: LLMRequest, model_id: str, start: float) -> LLMResponse:
        api_key = get_secret("OPENAI_API_KEY") or os.getenv("OPENAI_API_KEY")
        if not api_key:
            raise ProviderError("OPENAI_API_KEY is missing", provider="cloud", error_type="missing_api_key")

        provider = CloudLLMProvider(self.config.cloud_base_url, api_key)
        attempt = 0
        last_exc: ProviderError | None = None

        while attempt <= self.config.max_retries:
            try:
                result = provider.chat(
                    messages,
                    model=model_id,
                    temperature=request.temperature,
                    max_tokens=request.max_tokens,
                    json_schema=request.json_schema,
                    tools=request.tools,
                )
                return self._make_response(
                    text=result.text,
                    provider="cloud",
                    model_id=model_id,
                    start_time=start,
                    usage=result.usage,
                    raw=result.raw,
                    retry_count=attempt,
                )
            except ProviderError as exc:
                last_exc = exc
                status = exc.status_code or 0
                if status == 429 or status >= 500:
                    if attempt >= self.config.max_retries:
                        break
                    delay = self._backoff_delay(attempt)
                    time.sleep(delay)
                    attempt += 1
                    continue
                raise

        if last_exc:
            last_exc.retry_count = attempt
            raise last_exc

        raise ProviderError("Cloud LLM failed", provider="cloud", error_type="unknown")

    def _backoff_delay(self, attempt: int) -> float:
        base = self.config.backoff_base_ms / 1000.0
        jitter = random.random() * base
        return base * (2 ** attempt) + jitter

    def _make_response(
        self,
        *,
        text: str,
        provider: str,
        model_id: str,
        start_time: float,
        usage: dict | None = None,
        cache_hit: bool = False,
        route_reason: str = "cloud",
        raw: dict | None = None,
        retry_count: int = 0,
    ) -> LLMResponse:
        return LLMResponse(
            text=text,
            usage=usage,
            provider=provider,
            model_id=model_id,
            latency_ms=int((time.time() - start_time) * 1000),
            cache_hit=cache_hit,
            route_reason=route_reason,
            raw=raw,
            retry_count=retry_count,
        )

    def _build_messages(self, request: LLMRequest, items: list[ContextItem]) -> list[dict[str, Any]]:
        if request.render_messages:
            return request.render_messages(items)
        if request.messages:
            return request.messages
        raise ValueError("LLMRequest requires messages or render_messages")

    def _select_model(self, route: str, kind: str, ctx) -> str:
        if route == ROUTE_LOCAL:
            return self.config.local_code_model if kind == "code" else self.config.local_chat_model

        if ctx and ctx.settings:
            cloud_cfg = ctx.settings.get("llm_cloud") or ctx.settings.get("llm") or {}
            if cloud_cfg.get("model"):
                return cloud_cfg.get("model")
            if cloud_cfg.get("provider") == "openai" and cloud_cfg.get("base_url"):
                self.config.cloud_base_url = cloud_cfg.get("base_url")
        return self.config.cloud_model

    def _auto_switch_reason(self, request: LLMRequest, items: list[ContextItem], run_id: str | None, flags: PolicyFlags) -> str | None:
        if not flags.auto_cloud_enabled or not flags.cloud_allowed:
            return None

        if request.task_kind in {"heavy_writing", "long_form", "report"}:
            if all(item.sensitivity == "public" for item in items):
                return "heavy_writing"

        if all(item.source_type == "web_page_text" for item in items) and self._items_length(items) >= 1200:
            return "web_page_text_long"

        key = (run_id or "", request.preferred_model_kind)
        failures = self._local_failures.get(key, 0)
        if failures >= 2:
            return "local_failures"

        if request.preferred_model_kind == "code" and failures >= 1:
            return "code_local_failures"

        return None

    def _items_length(self, items: Iterable[ContextItem]) -> int:
        total = 0
        for item in items:
            if isinstance(item.content, str):
                total += len(item.content)
            else:
                total += len(json.dumps(item.content, ensure_ascii=False))
        return total

    def _items_summary_by_source(self, items: Iterable[ContextItem]) -> dict[str, int]:
        counts: dict[str, int] = {}
        for item in items:
            counts[item.source_type] = counts.get(item.source_type, 0) + 1
        return counts

    def _cache_key(self, route: str, model_id: str, request: LLMRequest, messages: list[dict[str, Any]]) -> str:
        payload = {
            "route": route,
            "model": model_id,
            "temperature": request.temperature,
            "max_tokens": request.max_tokens,
            "messages": messages,
            "json_schema": request.json_schema,
            "tools": request.tools,
        }
        raw = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        return hashlib.sha256(raw.encode("utf-8")).hexdigest()

    def _cache_get(self, run_id: str | None, key: str) -> LLMResponse | None:
        if not run_id:
            return None
        cached = self._cache.get(run_id, {}).get(key)
        if not cached:
            return None
        return LLMResponse(
            text=cached.text,
            usage=cached.usage,
            provider=cached.provider,
            model_id=cached.model_id,
            latency_ms=0,
            cache_hit=True,
            route_reason=cached.route_reason,
            status=cached.status,
            error_type=cached.error_type,
            http_status=cached.http_status,
            retry_count=cached.retry_count,
            raw=cached.raw,
        )

    def _cache_set(self, run_id: str | None, key: str, response: LLMResponse) -> None:
        if not run_id:
            return
        self._cache.setdefault(run_id, {})[key] = response

    def _check_budget(self, run_id: str, step_id: str | None) -> tuple[str, int, int] | None:
        if self.config.budget_per_run is not None:
            current_run = self._run_counts.get(run_id, 0)
            if current_run >= self.config.budget_per_run:
                return ("per_run", self.config.budget_per_run, current_run)
        if step_id and self.config.budget_per_step is not None:
            current_step = self._step_counts.get((run_id, step_id), 0)
            if current_step >= self.config.budget_per_step:
                return ("per_step", self.config.budget_per_step, current_step)
        return None

    def _increment_budget(self, run_id: str | None, step_id: str | None) -> None:
        if not run_id:
            return
        self._run_counts[run_id] = self._run_counts.get(run_id, 0) + 1
        if step_id:
            key = (run_id, step_id)
            self._step_counts[key] = self._step_counts.get(key, 0) + 1

    def _note_local_failure(self, run_id: str | None, kind: str) -> None:
        key = (run_id or "", kind)
        self._local_failures[key] = self._local_failures.get(key, 0) + 1

    def _note_local_result(self, run_id: str | None, kind: str, response: LLMResponse) -> None:
        key = (run_id or "", kind)
        if not response.text.strip():
            self._local_failures[key] = self._local_failures.get(key, 0) + 1
        else:
            self._local_failures[key] = 0

    def _emit(self, run_id: str | None, event_type: str, message: str, payload: dict[str, Any], *, task_id: str | None, step_id: str | None) -> None:
        if not run_id:
            return
        emit(run_id, event_type, message, payload, task_id=task_id, step_id=step_id)

    def _is_qa_mode(self, ctx) -> bool:
        raw = os.getenv("ASTRA_QA_MODE")
        if raw and raw.strip().lower() in {"1", "true", "yes", "on"}:
            return True
        if ctx and getattr(ctx, "run", None):
            meta = ctx.run.get("meta") or {}
            return bool(meta.get("qa_mode"))
        return False

    def _qa_response(self, request: LLMRequest) -> str:
        if request.json_schema:
            return "{\"qa_mode\": true}"
        if request.messages:
            return "QA mode: response stub."
        return "QA mode"


_BRAIN_SINGLETON: BrainRouter | None = None


def get_brain() -> BrainRouter:
    global _BRAIN_SINGLETON
    if _BRAIN_SINGLETON is None:
        _BRAIN_SINGLETON = BrainRouter()
    return _BRAIN_SINGLETON

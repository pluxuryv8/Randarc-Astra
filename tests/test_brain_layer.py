from __future__ import annotations

import threading
import time
from types import SimpleNamespace

from core.brain.providers import ProviderError, ProviderResult
from core.brain.router import BrainConfig, BrainRouter
from core.brain.types import LLMRequest
from core.llm_routing import ContextItem, PolicyFlags, sanitize_context_items


def _dummy_ctx():
    return SimpleNamespace(
        run={"id": "run-1"},
        task={"id": "task-1"},
        plan_step={"id": "step-1"},
        settings={},
    )


def test_queue_serializes_requests(monkeypatch):
    monkeypatch.setattr("core.brain.router.emit", lambda *args, **kwargs: None)

    cfg = BrainConfig.from_env()
    cfg.max_concurrency = 1
    router = BrainRouter(cfg)

    first_started = threading.Event()
    allow_finish = threading.Event()
    second_started = threading.Event()

    def slow_call(messages, request, model_id):
        if not first_started.is_set():
            first_started.set()
            allow_finish.wait(0.5)
        else:
            second_started.set()
        return ProviderResult(text="ok", usage=None, raw={})

    monkeypatch.setattr(router, "_call_local", slow_call)

    def build_messages(_items):
        return [{"role": "user", "content": "hi"}]

    request = LLMRequest(
        purpose="test",
        context_items=[ContextItem(content="hi", source_type="user_prompt", sensitivity="personal")],
        render_messages=build_messages,
        run_id="run-1",
        task_id="task-1",
        step_id="step-1",
    )

    ctx = _dummy_ctx()

    thread1 = threading.Thread(target=lambda: router.call(request, ctx))
    thread2 = threading.Thread(target=lambda: router.call(request, ctx))

    thread1.start()
    first_started.wait(0.2)
    thread2.start()
    time.sleep(0.1)

    assert not second_started.is_set()

    allow_finish.set()
    thread1.join(1)
    thread2.join(1)
    assert second_started.is_set()


def test_backoff_on_429(monkeypatch):
    monkeypatch.setattr("core.brain.router.emit", lambda *args, **kwargs: None)
    monkeypatch.setenv("OPENAI_API_KEY", "test")

    cfg = BrainConfig.from_env()
    cfg.max_retries = 2
    cfg.backoff_base_ms = 1
    router = BrainRouter(cfg)

    attempts = {"count": 0}

    class StubCloud:
        def __init__(self, base_url, api_key):
            self.base_url = base_url
            self.api_key = api_key

        def chat(self, messages, model, temperature=0.2, max_tokens=None, json_schema=None, tools=None):
            attempts["count"] += 1
            if attempts["count"] < 3:
                raise ProviderError("rate limit", provider="cloud", status_code=429, error_type="http_error")
            return ProviderResult(text="ok", usage=None, raw={})

    monkeypatch.setattr("core.brain.router.CloudLLMProvider", StubCloud)
    monkeypatch.setattr("time.sleep", lambda *_: None)

    def build_messages(_items):
        return [{"role": "user", "content": "hi"}]

    request = LLMRequest(
        purpose="test",
        context_items=[ContextItem(content="web", source_type="web_page_text", sensitivity="public")],
        render_messages=build_messages,
        run_id="run-1",
        task_id="task-1",
        step_id="step-1",
    )

    ctx = _dummy_ctx()
    response = router.call(request, ctx)

    assert response.text == "ok"
    assert attempts["count"] == 3


def test_sanitizer_removes_telegram():
    items = [
        ContextItem(content="secret", source_type="telegram_text", sensitivity="personal"),
        ContextItem(content="web", source_type="web_page_text", sensitivity="public"),
    ]
    result = sanitize_context_items(items, allow_financial_file=False, flags=PolicyFlags())
    assert result.removed_counts_by_source["telegram_text"] == 1


def test_sanitizer_removes_screenshot_text():
    items = [
        ContextItem(content="ocr", source_type="screenshot_text", sensitivity="confidential"),
        ContextItem(content="web", source_type="web_page_text", sensitivity="public"),
    ]
    result = sanitize_context_items(items, allow_financial_file=False, flags=PolicyFlags())
    assert result.removed_counts_by_source["screenshot_text"] == 1


def test_financial_file_requires_approval(monkeypatch):
    monkeypatch.setattr("core.brain.router.emit", lambda *args, **kwargs: None)

    cfg = BrainConfig.from_env()
    router = BrainRouter(cfg)

    approval_called = {"called": False}

    def _approval(*args, **kwargs):
        approval_called["called"] = True
        return False

    monkeypatch.setattr("core.brain.router.request_cloud_approval", _approval)
    monkeypatch.setattr(router, "_call_local", lambda messages, request, model_id: ProviderResult(text="ok", usage=None, raw={}))

    router._local_failures[("run-1", "chat")] = 2

    def build_messages(_items):
        return [{"role": "user", "content": "hi"}]

    request = LLMRequest(
        purpose="test",
        context_items=[ContextItem(content="bank", source_type="file_content", sensitivity="financial")],
        render_messages=build_messages,
        run_id="run-1",
        task_id="task-1",
        step_id="step-1",
    )

    ctx = _dummy_ctx()
    response = router.call(request, ctx)

    assert approval_called["called"] is True
    assert response.provider == "local"

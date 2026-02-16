from __future__ import annotations

import pytest

import core.intent_router as intent_router
from core.intent_router import INTENT_ACT, INTENT_ASK, INTENT_CHAT, IntentRouter
from core.semantic.decision import SemanticDecision, SemanticDecisionError, SemanticMemoryItem


def _semantic(
    *,
    intent: str,
    confidence: float = 0.9,
    memory_item: SemanticMemoryItem | None = None,
    plan_hint: list[str] | None = None,
    response_style_hint: str | None = None,
    user_visible_note: str | None = None,
) -> SemanticDecision:
    return SemanticDecision(
        intent=intent,
        confidence=confidence,
        memory_item=memory_item,
        plan_hint=plan_hint or [],
        response_style_hint=response_style_hint,
        user_visible_note=user_visible_note,
        raw={},
    )


def test_intent_act_from_semantic(monkeypatch):
    monkeypatch.setattr(
        intent_router,
        "decide_semantic",
        lambda *args, **kwargs: _semantic(intent=INTENT_ACT, plan_hint=["BROWSER_RESEARCH_UI"]),
    )

    router = IntentRouter(qa_mode=False)
    decision = router.decide("Найди источники по теме")

    assert decision.intent == INTENT_ACT
    assert decision.decision_path == "semantic"
    assert decision.plan_hint == ["BROWSER_RESEARCH_UI"]
    assert decision.act_hint is not None
    assert decision.act_hint.target == "COMPUTER"


def test_intent_act_web_research_targets_text_only(monkeypatch):
    monkeypatch.setattr(
        intent_router,
        "decide_semantic",
        lambda *args, **kwargs: _semantic(intent=INTENT_ACT, plan_hint=["WEB_RESEARCH"]),
    )

    router = IntentRouter(qa_mode=False)
    decision = router.decide("Найди в интернете формулу ковариации")

    assert decision.intent == INTENT_ACT
    assert decision.act_hint is not None
    assert decision.act_hint.target == "TEXT_ONLY"
    assert decision.plan_hint == ["WEB_RESEARCH"]


def test_intent_chat_with_memory_item(monkeypatch):
    monkeypatch.setattr(
        intent_router,
        "decide_semantic",
        lambda *args, **kwargs: _semantic(
            intent=INTENT_CHAT,
            memory_item=SemanticMemoryItem(
                kind="user_profile",
                text="Имя пользователя: Михаил.",
                evidence="меня Михаил зовут",
            ),
        ),
    )

    router = IntentRouter(qa_mode=False)
    decision = router.decide("кстати, меня Михаил зовут")

    assert decision.intent == INTENT_CHAT
    assert decision.memory_item is not None
    assert decision.memory_item["text"] == "Имя пользователя: Михаил."


def test_intent_ask_uses_user_visible_note(monkeypatch):
    monkeypatch.setattr(
        intent_router,
        "decide_semantic",
        lambda *args, **kwargs: _semantic(
            intent=INTENT_ASK,
            confidence=0.7,
            user_visible_note="Уточни, пожалуйста, цель запроса.",
        ),
    )

    router = IntentRouter(qa_mode=False)
    decision = router.decide("сделай это")

    assert decision.intent == INTENT_ASK
    assert decision.needs_clarification is True
    assert decision.questions == ["Уточни, пожалуйста, цель запроса."]


def test_semantic_error_propagates(monkeypatch):
    def _boom(*args, **kwargs):
        raise SemanticDecisionError("semantic_decision_invalid_json")

    monkeypatch.setattr(intent_router, "decide_semantic", _boom)
    router = IntentRouter(qa_mode=False)

    with pytest.raises(SemanticDecisionError):
        router.decide("тест")


def test_qa_mode_bypasses_semantic():
    router = IntentRouter(qa_mode=True)
    decision = router.decide("любой текст")

    assert decision.intent == INTENT_ACT
    assert decision.decision_path == "qa_mode"

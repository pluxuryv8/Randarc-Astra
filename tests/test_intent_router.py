from __future__ import annotations

from core.intent_router import INTENT_ACT, INTENT_ASK, INTENT_CHAT, IntentRouter


class DummyBrain:
    def call(self, request, ctx=None):
        raise AssertionError("Brain should not be called")


def test_intent_act_rules():
    router = IntentRouter(brain=DummyBrain())
    decision = router.decide("Открой браузер и посмотри сайт")
    assert decision.intent == INTENT_ACT
    assert decision.act_hint is not None
    assert decision.act_hint.target == "COMPUTER"
    assert decision.confidence >= 0.8


def test_intent_chat_rules():
    router = IntentRouter(brain=DummyBrain())
    decision = router.decide("Объясни, что такое дедупликация")
    assert decision.intent == INTENT_CHAT
    assert decision.confidence >= 0.7


def test_intent_ask_clarify_on_short():
    router = IntentRouter(brain=DummyBrain())
    decision = router.decide("сделай это")
    assert decision.intent == INTENT_ASK
    assert 1 <= len(decision.questions) <= 2


def test_intent_danger_flags():
    router = IntentRouter(brain=DummyBrain())
    decision = router.decide("Удали файл README.md")
    assert decision.intent == INTENT_ACT
    assert decision.act_hint is not None
    assert "delete_file" in decision.act_hint.danger_flags
    assert decision.act_hint.suggested_run_mode == "execute_confirm"


def test_intent_reminder_rule():
    router = IntentRouter(brain=DummyBrain())
    decision = router.decide("в 16:00 напомни купить хлеб")
    assert decision.intent == INTENT_ACT
    assert decision.act_hint is not None
    assert decision.act_hint.target == "TEXT_ONLY"


def test_intent_reminder_needs_time():
    router = IntentRouter(brain=DummyBrain())
    decision = router.decide("напомни купить хлеб")
    assert decision.intent == INTENT_ASK
    assert decision.questions

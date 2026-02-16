from __future__ import annotations

from core.brain.types import LLMResponse
from core.memory.interpreter import interpret_user_message_for_memory


class FakeBrain:
    def __init__(self, text: str, *, status: str = "ok") -> None:
        self._text = text
        self._status = status

    def call(self, request, ctx=None):
        return LLMResponse(
            text=self._text,
            usage=None,
            provider="local",
            model_id="fake",
            latency_ms=1,
            cache_hit=False,
            route_reason="test",
            status=self._status,
            error_type=None,
        )


def test_interpreter_extracts_name_and_addressing_preferences():
    brain = FakeBrain(
        """
        {
          "should_store": true,
          "confidence": 0.93,
          "facts": [
            {"key":"user.name","value":"Михаил","confidence":0.96,"evidence":"меня зовут Михаил"}
          ],
          "preferences": [
            {"key":"user.addressing.preference","value":"обращаться: Михаил","confidence":0.84,"evidence":"обращайся так"}
          ],
          "title": "Профиль пользователя",
          "summary": "Пользователь представился как Михаил и попросил обращаться по имени.",
          "possible_facts": []
        }
        """
    )
    user_text = "Запомни, меня зовут Михаил и обращайся так"
    result = interpret_user_message_for_memory(user_text, history=[], known_profile=None, brain=brain)
    assert result["should_store"] is True
    assert any(item["key"] == "user.name" and item["value"] == "Михаил" for item in result["facts"])


def test_interpreter_skips_small_talk():
    brain = FakeBrain(
        """
        {
          "should_store": false,
          "confidence": 0.31,
          "facts": [],
          "preferences": [],
          "title": "Профиль пользователя",
          "summary": "Нечего сохранять.",
          "possible_facts": []
        }
        """
    )
    result = interpret_user_message_for_memory("Привет", history=[], known_profile=None, brain=brain)
    assert result["should_store"] is False
    assert result["facts"] == []

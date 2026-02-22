from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from apps.api.routes import runs as runs_route
from core.agent import analyze_tone, build_explicit_style_memory_payload


def _pref_values(payload: dict | None) -> dict[str, str]:
    if not isinstance(payload, dict):
        return {}
    memory_payload = payload.get("memory_payload") if isinstance(payload.get("memory_payload"), dict) else {}
    preferences = memory_payload.get("preferences") if isinstance(memory_payload.get("preferences"), list) else []
    result: dict[str, str] = {}
    for item in preferences:
        if not isinstance(item, dict):
            continue
        key = item.get("key")
        value = item.get("value")
        if isinstance(key, str) and isinstance(value, str):
            result[key] = value
    return result


def test_character_scenario_strict_style():
    payload = build_explicit_style_memory_payload("Отвечай строго и формально.", [])
    prefs = _pref_values(payload)
    assert prefs.get("style.tone") == "strict"


def test_character_scenario_friendly_style():
    payload = build_explicit_style_memory_payload("Будь дружелюбнее и мягче в ответах.", [])
    prefs = _pref_values(payload)
    assert prefs.get("style.tone") == "friendly"


def test_character_scenario_humor():
    analysis = analyze_tone("Ахах, можно с легкой шуткой, но по делу", [])
    assert analysis["signals"]["humor_cues"] > 0
    assert "Witty/Humorous-lite" in analysis["candidate_modes"]


def test_character_scenario_neutral():
    hint = runs_route._contextual_tone_adaptation_hint(
        "привет, как дела",
        {"type": "neutral", "task_complex": False},
    )
    assert hint is None


def test_character_scenario_profanity():
    analysis = analyze_tone("Бля, это не работает, помоги быстро", [])
    assert analysis["type"] in {"frustrated", "crisis"}
    hint = runs_route._style_hint_from_tone_analysis(analysis)
    assert isinstance(hint, str)
    assert hint.strip() != ""


def test_character_scenario_short_format():
    mode, reason = runs_route._select_chat_response_mode("Ответь кратко: 2+2")
    assert mode == "direct_answer"
    assert reason == "simple_query"
    assert runs_route._user_requested_detailed_answer("Ответь кратко: 2+2", mode) is False


def test_character_scenario_long_format():
    detailed = runs_route._user_requested_detailed_answer(
        "Сделай подробно и пошагово, с деталями",
        "direct_answer",
    )
    assert detailed is True


def test_character_scenario_style_switch_in_dialog():
    history = [{"role": "user", "content": "Дай формулу ковариации"}]
    analysis = analyze_tone("Бля, ничего не работает, помоги", history)
    assert analysis["recall"]["detected_shift"] is True


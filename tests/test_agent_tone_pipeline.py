from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from core.agent import (
    analyze_tone,
    build_chat_system_prompt,
    build_tone_profile_memory_payload,
    load_persona_modules,
    merge_memory_payloads,
)


def test_analyze_tone_detects_dry_query():
    analysis = analyze_tone("Дай формулу ковариации", [])
    assert analysis["type"] == "dry"
    assert analysis["mirror_level"] == "low"
    assert analysis["path"] == "fast"


def test_analyze_tone_detects_frustration_and_shift():
    history = [{"role": "user", "content": "Дай формулу ковариации"}]
    analysis = analyze_tone("Бля, как я устал от этого кода!!!", history)
    assert analysis["type"] == "frustrated"
    assert analysis["mirror_level"] in {"medium", "high"}
    assert analysis["recall"]["detected_shift"] is True


def test_build_chat_system_prompt_uses_fast_path_for_simple_dry_query():
    prompt, analysis = build_chat_system_prompt(
        [],
        None,
        user_message="Дай формулу ковариации",
        history=[],
        owner_direct_mode=True,
    )
    assert "[Core Identity]" in prompt
    assert "[Tone Pipeline]" not in prompt
    assert "[Variation Rules]" not in prompt
    assert "[Variation Runtime]" not in prompt
    assert analysis["type"] == "dry"
    assert analysis["path"] == "fast"


def test_build_chat_system_prompt_keeps_full_path_for_frustrated_query():
    prompt, analysis = build_chat_system_prompt(
        [],
        None,
        user_message="Бля, я заебался и всё бесит, помоги быстро.",
        history=[],
        owner_direct_mode=True,
    )
    assert "[Tone Pipeline]" in prompt
    assert "[Variation Rules]" in prompt
    assert "[Variation Runtime]" in prompt
    assert analysis["path"] == "full"


def test_build_chat_system_prompt_keeps_full_path_for_fatigued_distress_query():
    prompt, analysis = build_chat_system_prompt(
        [],
        None,
        user_message="Я устал, ничего не работает, что делать?",
        history=[],
        owner_direct_mode=True,
    )
    assert "[Tone Pipeline]" in prompt
    assert "[Variation Rules]" in prompt
    assert "[Variation Runtime]" in prompt
    assert analysis["path"] == "full"


def test_tone_memory_payload_merges_into_existing_payload():
    tone = analyze_tone("Бля ебать, устал от этого кода", [])
    tone_payload = build_tone_profile_memory_payload("Бля ебать, устал от этого кода", tone, [])
    assert tone_payload is not None
    assert any(item.get("key") == "style.tone" for item in tone_payload["memory_payload"]["preferences"])

    primary = {
        "content": "кстати меня Михаил зовут",
        "origin": "auto",
        "memory_payload": {
            "title": "Профиль пользователя",
            "summary": "Пользователь представился как Михаил.",
            "confidence": 0.93,
            "facts": [{"key": "user.name", "value": "Михаил", "confidence": 0.93, "evidence": "меня Михаил зовут"}],
            "preferences": [],
            "possible_facts": [],
        },
    }
    merged = merge_memory_payloads(primary, tone_payload)
    assert merged is not None
    assert any(item.get("key") == "user.name" for item in merged["memory_payload"]["facts"])
    assert any(item.get("key") == "style.tone" for item in merged["memory_payload"]["preferences"])


def test_persona_prompt_modules_share_style_contract():
    persona = load_persona_modules()

    for key in ("core_identity", "tone_pipeline", "variation_rules"):
        block = persona[key]
        assert "Shared Style Contract (v2)" in block
        assert "full improvisation via self-reflection" in block
        assert "step-by-step plan" in block
        assert "direct answer" in block

    assert "Creative-Deep" in persona["core_identity"]
    assert "Steady" in persona["core_identity"]
    assert "Нумерованные шаги `1..N` разрешены" in persona["variation_rules"]
    assert "Tone pipeline не переопределяет response-mode" in persona["tone_pipeline"]

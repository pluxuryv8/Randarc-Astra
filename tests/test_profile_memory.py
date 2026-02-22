from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from apps.api.routes import runs as runs_route
from core.brain.types import LLMRequest, LLMResponse
from core.chat_context import build_memory_dump_response
from core.skill_context import SkillContext
from memory import store
from skills.memory_save import skill as memory_skill


def _init_store(tmp_path: Path):
    os.environ["ASTRA_DATA_DIR"] = str(tmp_path)
    store.reset_for_tests()
    store.init(tmp_path, ROOT / "memory" / "migrations")


def test_memory_save_name(tmp_path: Path):
    _init_store(tmp_path)
    project = store.create_project("Mem", [], {})
    run = store.create_run(project["id"], "кстати, меня Михаил зовут", "execute_confirm")

    step = {
        "id": "step-memory",
        "run_id": run["id"],
        "step_index": 0,
        "title": "Сохранить в память",
        "skill_name": "memory_save",
        "inputs": {"content": run["query_text"], "facts": ["Имя пользователя: Михаил."]},
        "depends_on": [],
        "status": "created",
        "kind": "MEMORY_COMMIT",
        "success_criteria": "ok",
        "danger_flags": [],
        "requires_approval": False,
        "artifacts_expected": [],
    }
    store.insert_plan_steps(run["id"], [step])
    task = store.create_task(run["id"], step["id"], attempt=1)

    ctx = SkillContext(run=run, plan_step=step, task=task, settings={}, base_dir=str(ROOT))
    memory_skill.run(step["inputs"], ctx)

    items = store.list_user_memories()
    assert any("Михаил" in item.get("content", "") for item in items)


def test_memory_dump_uses_profile_items(tmp_path: Path):
    _init_store(tmp_path)
    store.create_user_memory(None, "Имя пользователя: Михаил.", [])
    store.create_user_memory(None, "Предпочтение пользователя: короткие ответы.", [])

    items = store.list_user_memories()
    response = build_memory_dump_response(items)

    assert "Вот что я помню о тебе" in response
    assert "Михаил" in response
    assert "короткие ответы" in response


def test_memory_dump_empty():
    response = build_memory_dump_response([])
    assert "Пока ничего не помню" in response


def test_chat_system_prompt_uses_name_and_style_from_profile(tmp_path: Path):
    _init_store(tmp_path)
    store.create_user_memory(
        "Профиль пользователя",
        "Пользователь представился как Михаил.",
        [],
        meta={
            "summary": "Пользователь представился как Михаил.",
            "facts": [{"key": "user.name", "value": "Михаил", "confidence": 0.95, "evidence": "меня зовут Михаил"}],
            "preferences": [{"key": "style.brevity", "value": "short", "confidence": 0.86}],
        },
    )
    memories = store.list_user_memories()
    prompt = runs_route._build_chat_system_prompt(memories, None)
    assert "Имя пользователя: Михаил." in prompt
    assert "Отвечай коротко и по делу." in prompt


def test_chat_system_prompt_maps_strict_tone_preference_from_profile(tmp_path: Path):
    _init_store(tmp_path)
    store.create_user_memory(
        "Профиль пользователя",
        "Пользователь попросил строгий и краткий стиль ответов.",
        [],
        meta={
            "summary": "Пользователь попросил строгий и краткий стиль ответов.",
            "preferences": [
                {"key": "style.tone", "value": "strict", "confidence": 0.92},
                {"key": "style.brevity", "value": "short", "confidence": 0.9},
            ],
        },
    )
    memories = store.list_user_memories()
    prompt = runs_route._build_chat_system_prompt(memories, None)

    assert "Стиль: строгий и точный, без лишней разговорности." in prompt
    assert "Отвечай коротко и по делу." in prompt


def test_style_hint_from_interpretation_maps_friendly_and_brief_preferences():
    hint = runs_route._style_hint_from_interpretation(
        {
            "preferences": [
                {"key": "style.tone", "value": "friendly", "confidence": 0.9},
                {"key": "style.brevity", "value": "short", "confidence": 0.9},
            ]
        }
    )

    assert hint is not None
    assert "дружелюбный" in hint.lower()
    assert "коротко" in hint.lower()


def test_effective_response_style_hint_combines_preference_context_and_precision_guard():
    hint = runs_route._build_effective_response_style_hint(
        decision_style_hint=None,
        interpreted_style_hint="Стиль: дружелюбный и поддерживающий.",
        tone_style_hint="Коротко валидируй состояние и сразу предложи конкретный план.",
        profile_style_hints=["Отвечай коротко и по делу."],
        query_text="Составь SQL-план с лимитами 100 и 200 и метриками контроля.",
        tone_analysis={"type": "frustrated", "task_complex": True},
    )

    assert hint is not None
    lowered = hint.lower()
    assert "дружелюбный" in lowered
    assert "конкретный план" in lowered
    assert "не искажай факты" in lowered


def test_effective_response_style_hint_keeps_decision_priority_and_context_guard():
    hint = runs_route._build_effective_response_style_hint(
        decision_style_hint="Стиль ответа: формально и строго.",
        interpreted_style_hint="Стиль: дружелюбный и поддерживающий.",
        tone_style_hint=None,
        profile_style_hints=["Отвечай коротко и по делу."],
        query_text="Дай формулу и точные числа для расчета.",
        tone_analysis={"type": "dry", "task_complex": False},
    )

    assert hint is not None
    lowered = hint.lower()
    assert "формально и строго" in lowered
    assert "дружелюбный" not in lowered
    assert "не искажай факты" in lowered


def test_contextual_tone_adaptation_hint_is_none_for_neutral_smalltalk():
    hint = runs_route._contextual_tone_adaptation_hint(
        "привет, как дела",
        {"type": "neutral", "task_complex": False},
    )
    assert hint is None


def test_selected_response_style_meta_exposes_diagnostics_without_text_leak():
    meta = runs_route._build_selected_response_style_meta(
        decision_style_hint=None,
        interpreted_style_hint="Стиль: дружелюбный и поддерживающий.",
        tone_style_hint="Коротко валидируй состояние и сразу предложи конкретный план.",
        profile_style_hints=["Отвечай коротко и по делу."],
        query_text="Составь план с KPI и лимитами 100 и 200.",
        tone_analysis={"type": "frustrated", "task_complex": True},
        response_mode="direct_answer",
    )

    assert meta["response_mode"] == "direct_answer"
    assert meta["detail_requested"] is False
    assert "memory_interpreter" in meta["sources"]
    assert "tone_analysis" in meta["sources"]
    assert "contextual_adaptation" in meta["sources"]
    assert isinstance(meta["selected_style"], str)
    assert "не искажай факты" in str(meta["selected_style"]).lower()


def test_selected_response_style_meta_marks_detailed_request():
    meta = runs_route._build_selected_response_style_meta(
        decision_style_hint=None,
        interpreted_style_hint=None,
        tone_style_hint=None,
        profile_style_hints=[],
        query_text="Сделай подробно и пошагово",
        tone_analysis={"type": "neutral", "task_complex": False},
        response_mode="direct_answer",
    )
    assert meta["detail_requested"] is True


def test_chat_system_prompt_owner_direct_mode_toggle(monkeypatch):
    monkeypatch.setenv("ASTRA_OWNER_DIRECT_MODE", "true")
    prompt_direct = runs_route._build_chat_system_prompt([], None)
    assert "Режим владельца: ON." in prompt_direct

    monkeypatch.setenv("ASTRA_OWNER_DIRECT_MODE", "false")
    prompt_default = runs_route._build_chat_system_prompt([], None)
    assert "Режим владельца: OFF." in prompt_default


def test_chat_inference_defaults(monkeypatch):
    monkeypatch.delenv("ASTRA_LLM_CHAT_TEMPERATURE", raising=False)
    monkeypatch.delenv("ASTRA_LLM_CHAT_TOP_P", raising=False)
    monkeypatch.delenv("ASTRA_LLM_CHAT_REPEAT_PENALTY", raising=False)
    monkeypatch.delenv("ASTRA_LLM_OLLAMA_NUM_PREDICT", raising=False)

    assert runs_route._chat_temperature_default() == 0.35
    assert runs_route._chat_top_p_default() == 0.9
    assert runs_route._chat_repeat_penalty_default() == 1.15
    assert runs_route._chat_num_predict_default() == 256


def test_chat_inference_settings_adapt_to_complexity(monkeypatch):
    monkeypatch.setenv("ASTRA_LLM_CHAT_TEMPERATURE", "0.42")
    monkeypatch.setenv("ASTRA_LLM_CHAT_TOP_P", "0.88")
    monkeypatch.setenv("ASTRA_LLM_CHAT_REPEAT_PENALTY", "1.2")
    monkeypatch.setenv("ASTRA_LLM_OLLAMA_NUM_PREDICT", "300")

    fast = runs_route._chat_inference_settings("2+2?", response_mode="direct_answer")
    complex_case = runs_route._chat_inference_settings(
        "Составь подробный план тренировок на месяц с этапами, рисками и метриками прогресса",
        response_mode="step_by_step_plan",
    )

    assert fast["profile"] == "fast"
    assert fast["profile_reason"] == "short_query"
    assert fast["max_tokens"] < 300
    assert fast["temperature"] < 0.42
    assert fast["top_p"] < 0.88
    assert fast["repeat_penalty"] > 1.2

    assert complex_case["profile"] == "complex"
    assert "response_mode_plan" in complex_case["profile_reason"]
    assert complex_case["max_tokens"] > 300
    assert complex_case["temperature"] < 0.42
    assert complex_case["top_p"] > 0.88
    assert complex_case["repeat_penalty"] > 1.2


def test_chat_soft_retry_heuristics():
    assert runs_route._soft_retry_reason("Сделай это", "Как ИИ я не могу помочь в этом.") == "unwanted_prefix"
    assert (
        runs_route._soft_retry_reason(
            "Составь план тренировок на неделю",
            "Вот универсальный шаблон ответа. Это зависит от контекста, уточните детали.",
        )
        == "template_like"
    )
    assert runs_route._soft_retry_reason("Сделай это", "Сделай следующее...") == "truncated"
    assert runs_route._soft_retry_reason("Привет, как дела?", "Hello there") == "ru_language_mismatch"
    assert (
        runs_route._soft_retry_reason(
            "Как пытали канеки Кена в токийском гуле",
            "Давайте сначала поговорим о текущей проблеме.",
        )
        == "off_topic"
    )
    assert (
        runs_route._soft_retry_reason(
            "Как пытали канеки Кена в токийском гуле",
            "В 1980 году я попал на вечеринку в Токио и пытался выпить из канеки Кена.",
        )
        == "off_topic"
    )
    assert (
        runs_route._soft_retry_reason(
            "Как пытали канеки Кена в токийском гуле",
            "Пока не слышала, но предполагаю, что это было намного интереснее, чем обычный гул.",
        )
        == "off_topic"
    )
    assert (
        runs_route._soft_retry_reason(
            "А сюжет хентая эйфория знаешь?",
            "Хентай - жанр с элементами фантастического сюжета и различными стилями.",
        )
        == "off_topic"
    )
    assert runs_route._soft_retry_reason("Привет, как дела?", "Привет! Всё нормально.") is None


def test_auto_web_research_trigger_heuristics(monkeypatch):
    monkeypatch.setenv("ASTRA_CHAT_AUTO_WEB_RESEARCH_ENABLED", "true")

    assert runs_route._should_auto_web_research(
        "А сюжет хентая эйфория знаешь?",
        "Хентай - жанр с элементами фантастического сюжета и различными стилями.",
        error_type=None,
    )
    assert runs_route._should_auto_web_research(
        "Кто такой Кен Канеки?",
        "Не знаю точно, возможно это персонаж аниме.",
        error_type=None,
    )
    assert not runs_route._should_auto_web_research(
        "привет",
        "Не знаю.",
        error_type=None,
    )


def test_auto_web_research_skips_when_answer_is_relevant_and_structured(monkeypatch):
    monkeypatch.setenv("ASTRA_CHAT_AUTO_WEB_RESEARCH_ENABLED", "true")
    query = "Кто такой Кен Канеки?"
    answer = (
        "Краткий итог: Кен Канеки - главный герой манги и аниме Tokyo Ghoul.\n\n"
        "Детали:\n"
        "Он студент, чья жизнь меняется после встречи с гулем. "
        "Дальше сюжет строится вокруг его конфликта между человеческой и гулей природой."
    )

    should_research, reason = runs_route._auto_web_research_decision(query, answer, error_type=None)

    assert should_research is False
    assert reason is None


def test_auto_web_research_triggers_for_short_uncertain_answer(monkeypatch):
    monkeypatch.setenv("ASTRA_CHAT_AUTO_WEB_RESEARCH_ENABLED", "true")
    query = "Кто такой Кен Канеки?"
    answer = "Не уверен, возможно это персонаж из аниме."

    should_research, reason = runs_route._auto_web_research_decision(query, answer, error_type=None)

    assert should_research is True
    assert reason in {"uncertain_response", "off_topic"}


def test_user_visible_answer_sanitizes_internal_reasoning():
    raw = (
        "<think>Проверяю источники и сравниваю версии.</think>\n"
        "Internal reasoning:\n"
        "- сначала проверю контекст\n"
        "Final answer: Кен Канеки - главный герой Tokyo Ghoul."
    )
    clean = runs_route._sanitize_user_visible_answer(raw)

    assert "<think>" not in clean
    assert "Internal reasoning" not in clean
    assert "Final answer" not in clean
    assert "Кен Канеки" in clean


class _SequenceBrain:
    def __init__(self, responses: list[LLMResponse]) -> None:
        self._responses = list(responses)
        self.calls: list[LLMRequest] = []

    def call(self, request, ctx=None):  # noqa: ANN001, ANN002
        self.calls.append(request)
        idx = len(self.calls) - 1
        if idx >= len(self._responses):
            return self._responses[-1]
        return self._responses[idx]


def _llm_response(text: str, *, status: str = "ok") -> LLMResponse:
    return LLMResponse(
        text=text,
        usage=None,
        provider="local",
        model_id="fake",
        latency_ms=1,
        cache_hit=False,
        route_reason="test",
        status=status,
        error_type=None,
    )


def _chat_request(user_text: str) -> LLMRequest:
    return LLMRequest(
        purpose="chat_response",
        task_kind="chat",
        run_id="run-test",
        messages=[
            {"role": "system", "content": "system"},
            {"role": "user", "content": user_text},
        ],
    )


def test_chat_safe_retry_runs_once_for_empty_response():
    brain = _SequenceBrain(
        [
            _llm_response(""),
            _llm_response("Кен Канеки - главный герой Tokyo Ghoul."),
        ]
    )

    request = _chat_request("Кто такой Кен Канеки?")
    result = runs_route._call_chat_with_soft_retry(brain, request, ctx=None)

    assert len(brain.calls) == 2
    assert brain.calls[0].purpose == "chat_response"
    assert brain.calls[1].purpose == "chat_response_base_fallback"
    assert brain.calls[1].messages == request.messages
    assert result.text == "Кен Канеки - главный герой Tokyo Ghoul."


def test_chat_safe_retry_runs_once_for_off_topic_response():
    brain = _SequenceBrain(
        [
            _llm_response("Давайте обсудим продуктивность и тайм-менеджмент."),
            _llm_response("Кен Канеки - главный герой Tokyo Ghoul."),
        ]
    )

    request = _chat_request("Кто такой Кен Канеки?")
    result = runs_route._call_chat_with_soft_retry(brain, request, ctx=None)

    assert len(brain.calls) == 2
    assert brain.calls[1].purpose == "chat_response_base_fallback"
    assert result.text == "Кен Канеки - главный герой Tokyo Ghoul."


def test_chat_safe_retry_is_not_repeated_when_retry_still_bad():
    brain = _SequenceBrain(
        [
            _llm_response("Давайте обсудим продуктивность и тайм-менеджмент."),
            _llm_response("Я в целом не уверен, возможно тут есть разные версии."),
        ]
    )

    request = _chat_request("Кто такой Кен Канеки?")
    _ = runs_route._call_chat_with_soft_retry(brain, request, ctx=None)

    assert len(brain.calls) == 2


def test_chat_safe_retry_regenerates_template_like_answer():
    brain = _SequenceBrain(
        [
            _llm_response("Вот универсальный шаблон ответа. Это зависит от контекста, уточните детали."),
            _llm_response("Кен Канеки - главный герой Tokyo Ghoul."),
        ]
    )

    request = _chat_request("Кто такой Кен Канеки?")
    result = runs_route._call_chat_with_soft_retry(brain, request, ctx=None)

    assert len(brain.calls) == 2
    assert brain.calls[1].purpose == "chat_response_base_fallback"
    assert result.text == "Кен Канеки - главный герой Tokyo Ghoul."


def test_chat_response_mode_selector_boundary_simple_vs_complex():
    simple_mode, simple_reason = runs_route._select_chat_response_mode("214 + 43241")
    complex_mode, complex_reason = runs_route._select_chat_response_mode(
        "Составь подробный план тренировок на месяц с этапами, рисками и метриками прогресса"
    )

    assert simple_mode == "direct_answer"
    assert simple_reason == "simple_query"
    assert complex_mode == "step_by_step_plan"
    assert "complex_keyword" in complex_reason


def test_chat_system_prompt_contains_selected_response_mode():
    direct_prompt = runs_route._build_chat_system_prompt([], None, response_mode="direct_answer")
    plan_prompt = runs_route._build_chat_system_prompt([], None, response_mode="step_by_step_plan")

    assert "Формат ответа: direct answer." in direct_prompt
    assert "Формат ответа: step-by-step plan." in plan_prompt


def test_chat_context_selector_keeps_recent_and_relevant_history(monkeypatch):
    monkeypatch.setenv("ASTRA_CHAT_CONTEXT_MAX_MESSAGES", "4")
    monkeypatch.setenv("ASTRA_CHAT_CONTEXT_MIN_RECENT_MESSAGES", "2")
    monkeypatch.setenv("ASTRA_CHAT_CONTEXT_MAX_CHARS", "240")
    monkeypatch.setenv("ASTRA_CHAT_CONTEXT_MESSAGE_MAX_CHARS", "90")

    history = [
        {"role": "user", "content": "Напомни, что Кен Канеки главный герой Tokyo Ghoul."},
        {"role": "assistant", "content": "Принял."},
        {"role": "user", "content": "Какая сегодня погода в Москве?"},
        {"role": "assistant", "content": "Сейчас уточню."},
        {"role": "user", "content": "И еще важно, ответ коротко."},
        {"role": "assistant", "content": "Хорошо, отвечу кратко."},
    ]
    selected = runs_route._select_chat_history_for_prompt(history, user_text="Кто такой Кен Канеки?")

    assert len(selected) <= 4
    assert selected[-2]["content"] == "И еще важно, ответ коротко."
    assert selected[-1]["content"] == "Хорошо, отвечу кратко."
    assert any("Кен Канеки" in item["content"] for item in selected)
    assert runs_route._history_text_char_count(selected) <= 240


def test_profile_memory_selector_keeps_core_and_query_relevant(monkeypatch):
    monkeypatch.setenv("ASTRA_CHAT_CONTEXT_MEMORY_MAX_ITEMS", "4")
    monkeypatch.setenv("ASTRA_CHAT_CONTEXT_MEMORY_MAX_CHARS", "80")
    monkeypatch.setenv("ASTRA_CHAT_CONTEXT_MEMORY_ITEM_MAX_CHARS", "220")

    memories = [
        {
            "title": "Профиль пользователя",
            "content": "Пользователь представился как Михаил.",
            "meta": {"facts": [{"key": "user.name", "value": "Михаил"}]},
            "pinned": False,
        },
        {
            "title": "Разное",
            "content": "Пользователь любит кофе по утрам. " * 12,
            "meta": {},
            "pinned": False,
        },
        {
            "title": "Аниме",
            "content": "Кен Канеки - герой Tokyo Ghoul. " * 12,
            "meta": {"summary": "Кен Канеки - герой Tokyo Ghoul. " * 12},
            "pinned": False,
        },
    ]

    selected = runs_route._select_profile_memories_for_prompt(memories, user_text="Кто такой Кен Канеки?")
    selected_texts = [runs_route._memory_summary_text(item) for item in selected]

    assert len(selected) == 2
    assert any("Михаил" in text for text in selected_texts)
    assert any("Кен Канеки" in text for text in selected_texts)
    assert runs_route._memory_text_char_count(selected) <= 260


def test_final_output_postprocessor_builds_summary_details_and_dedupes():
    raw = (
        "План на неделю: начни с умеренного дефицита калорий и ходьбы.\n\n"
        "План на неделю: начни с умеренного дефицита калорий и ходьбы.\n\n"
        "###!!!###\n"
        "День 1: кардио 30 минут.\n"
        "День 2: силовая тренировка на всё тело.\n\n"
        "Источники:\n"
        "- Example A - https://example.org/a\n"
        "- Example A - https://example.org/a\n"
        "- Example B - https://example.org/b"
    )

    clean = runs_route._finalize_user_visible_answer(raw)

    assert clean.startswith("Краткий итог:")
    assert "\n\nДетали:\n" in clean
    assert "###!!!###" not in clean
    assert clean.count("План на неделю: начни с умеренного дефицита калорий и ходьбы.") == 1
    assert clean.count("https://example.org/a") == 1
    assert clean.count("https://example.org/b") == 1


def test_final_output_postprocessor_keeps_short_answer_compact():
    text = "Кен Канеки - главный герой Tokyo Ghoul."
    clean = runs_route._finalize_user_visible_answer(text)
    assert clean == text


def test_final_output_postprocessor_removes_toxic_noise_line():
    raw = (
        "Краткий итог: Нужен план действий на 14 дней.\n"
        "Ты дебил, если этого не понимаешь.\n"
        "1. Зафиксируй обязательные расходы.\n"
        "2. Сократи необязательные траты.\n"
        "3. Контролируй cash-flow каждый день."
    )

    clean = runs_route._finalize_user_visible_answer(raw)

    assert "дебил" not in clean.lower()
    assert "Зафиксируй обязательные расходы" in clean
    assert "Контролируй cash-flow каждый день" in clean


def test_chat_brevity_limit_compacts_direct_answer_when_not_requested(monkeypatch):
    monkeypatch.setenv("ASTRA_CHAT_COMPACT_MAX_CHARS", "180")
    monkeypatch.setenv("ASTRA_CHAT_COMPACT_MAX_LINES", "4")
    monkeypatch.setenv("ASTRA_CHAT_COMPACT_MAX_DETAIL_LINES", "3")

    raw = (
        "Краткий итог: Нужен план на неделю для снижения веса.\n\n"
        "Детали:\n"
        "1. Зафиксируй базовую калорийность и цель по дефициту.\n"
        "2. Составь меню с белком в каждом приеме пищи.\n"
        "3. Добавь 8-10 тысяч шагов ежедневно.\n"
        "4. Сделай 3 силовые тренировки в неделю.\n"
        "5. Взвешивайся каждое утро и записывай тренд.\n"
        "6. Раз в неделю корректируй калории по факту прогресса.\n"
        "7. Проверь сон и восстановление."
    )

    compact = runs_route._finalize_chat_user_visible_answer(
        raw,
        user_text="Сделай план на неделю",
        response_mode="direct_answer",
    )

    assert "Краткий итог:" in compact
    assert "\n…".strip() in compact
    assert "6." not in compact
    assert "7." not in compact


def test_chat_brevity_limit_preserves_full_answer_for_detailed_request(monkeypatch):
    monkeypatch.setenv("ASTRA_CHAT_COMPACT_MAX_CHARS", "180")
    monkeypatch.setenv("ASTRA_CHAT_COMPACT_MAX_LINES", "4")
    monkeypatch.setenv("ASTRA_CHAT_COMPACT_MAX_DETAIL_LINES", "3")

    raw = (
        "Краткий итог: Нужен план на неделю для снижения веса.\n\n"
        "Детали:\n"
        "1. Зафиксируй базовую калорийность и цель по дефициту.\n"
        "2. Составь меню с белком в каждом приеме пищи.\n"
        "3. Добавь 8-10 тысяч шагов ежедневно.\n"
        "4. Сделай 3 силовые тренировки в неделю.\n"
        "5. Взвешивайся каждое утро и записывай тренд."
    )

    baseline = runs_route._finalize_user_visible_answer(raw)
    detailed = runs_route._finalize_chat_user_visible_answer(
        raw,
        user_text="Сделай подробно и пошагово, пожалуйста",
        response_mode="direct_answer",
    )

    assert detailed == baseline


def test_chat_brevity_limit_preserves_full_answer_for_step_mode(monkeypatch):
    monkeypatch.setenv("ASTRA_CHAT_COMPACT_MAX_CHARS", "180")
    monkeypatch.setenv("ASTRA_CHAT_COMPACT_MAX_LINES", "4")
    monkeypatch.setenv("ASTRA_CHAT_COMPACT_MAX_DETAIL_LINES", "3")

    raw = (
        "Краткий итог: Нужен план на неделю для снижения веса.\n\n"
        "Детали:\n"
        "1. Зафиксируй базовую калорийность и цель по дефициту.\n"
        "2. Составь меню с белком в каждом приеме пищи.\n"
        "3. Добавь 8-10 тысяч шагов ежедневно.\n"
        "4. Сделай 3 силовые тренировки в неделю.\n"
        "5. Взвешивайся каждое утро и записывай тренд."
    )

    baseline = runs_route._finalize_user_visible_answer(raw)
    detailed = runs_route._finalize_chat_user_visible_answer(
        raw,
        user_text="Сделай план",
        response_mode="step_by_step_plan",
    )

    assert detailed == baseline


def test_chat_noisy_output_rebuilds_from_valid_fragments():
    raw = (
        "百度百科: случайный шум и мусор.\n"
        "####!!!!!####\n"
        "Краткий итог: Кен Канеки - главный герой Tokyo Ghoul.\n"
        "1. Факт подтверждается в нескольких источниках.\n"
        "2. Есть разные адаптации и версии сюжета."
    )
    clean = runs_route._finalize_chat_user_visible_answer(
        raw,
        user_text="кто такой кен канеки",
        response_mode="direct_answer",
    )

    assert "百度" not in clean
    assert "####!!!!!####" not in clean
    assert "Краткий итог:" in clean
    assert "Кен Канеки" in clean


def test_chat_noisy_output_falls_back_when_no_valid_fragments():
    raw = "百度百科 百度百科 ####!!!!!#### 。。。。"
    clean = runs_route._finalize_chat_user_visible_answer(
        raw,
        user_text="кто такой кен канеки",
        response_mode="direct_answer",
    )

    assert clean.startswith("Краткий итог:")
    assert "Не удалось стабильно получить ответ от модели." in clean
    assert "кто такой кен канеки" in clean


def test_chat_resilience_text_is_useful_and_structured():
    text = runs_route._chat_resilience_text("connection_error", user_text="кто такой кен канеки")
    assert text.startswith("Краткий итог:")
    assert "Локальная модель сейчас недоступна." in text
    assert "Текущий запрос: кто такой кен канеки." in text
    assert "\n\nДетали:\n1." in text

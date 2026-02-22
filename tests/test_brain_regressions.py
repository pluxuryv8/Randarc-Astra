from __future__ import annotations

import os
import re
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from apps.api.routes import runs as runs_route
from core import planner
from core.chat_context import build_chat_messages
from core.skills.result_types import ArtifactCandidate, SkillResult, SourceCandidate
from memory import store


def _init_db(tmp_path: Path) -> None:
    os.environ["ASTRA_DATA_DIR"] = str(tmp_path)
    store.reset_for_tests()
    store.init(tmp_path, ROOT / "memory" / "migrations")


def _create_chat_run(project_id: str, text: str, parent_run_id: str | None = None) -> dict:
    run = store.create_run(
        project_id,
        text,
        "plan_only",
        parent_run_id=parent_run_id,
        purpose="chat_only",
        meta={"intent": "CHAT"},
    )
    store.add_event(
        run["id"],
        "chat_response_generated",
        "info",
        "Ответ сформирован",
        payload={"text": f"Ответ на: {text}"},
    )
    return run


def test_regression_complex_weight_loss_query_marks_dirty_answer_for_repair(monkeypatch: pytest.MonkeyPatch) -> None:
    # Pass criteria:
    # 1) dirty/non-russian output is recognized as broken for this russian query
    # 2) fallback web-research path is considered necessary
    monkeypatch.setenv("ASTRA_CHAT_AUTO_WEB_RESEARCH_ENABLED", "true")
    query = "подготовь мне план тренировок на неделю чтобы похудеть со 120 кг до 90"
    dirty_answer = "百度百科: Workout plan ... maybe maybe ???"

    reason = runs_route._soft_retry_reason(query, dirty_answer)

    assert reason in {"ru_language_mismatch", "off_topic"}
    assert runs_route._should_auto_web_research(query, dirty_answer, error_type=None) is True


def test_regression_dirty_search_output_is_structured_and_deduplicated(tmp_path: Path) -> None:
    # Pass criteria:
    # 1) final answer is returned from artifact text
    # 2) source urls are deduplicated
    # 3) "Источники" block is appended once at the bottom
    answer_path = tmp_path / "web_answer.md"
    answer_path.write_text("Краткий итог: проверил источники и собрал ответ.", encoding="utf-8")

    result = SkillResult(
        what_i_did="Собрал и сверил источники.",
        artifacts=[
            ArtifactCandidate(
                type="web_research_answer_md",
                title="answer",
                content_uri=str(answer_path),
            )
        ],
        sources=[
            SourceCandidate(url="https://example.com/a", title="Источник A"),
            SourceCandidate(url="https://example.com/a", title="Источник A duplicate"),
            SourceCandidate(url="https://example.com/b", title="Источник B"),
        ],
    )

    text = runs_route._compose_web_research_chat_text(result)

    assert "Краткий итог: проверил источники и собрал ответ." in text
    assert text.count("Источники:") == 1
    assert text.count("https://example.com/a") == 1
    assert text.count("https://example.com/b") == 1


def test_regression_web_research_chat_text_enforces_summary_details_layout(tmp_path: Path) -> None:
    answer_path = tmp_path / "web_answer.md"
    answer_path.write_text(
        "Проверил несколько источников и собрал главные факты. "
        "Нужно обратить внимание на ограничения по данным.",
        encoding="utf-8",
    )

    result = SkillResult(
        what_i_did="Собрал и сверил источники.",
        artifacts=[
            ArtifactCandidate(
                type="web_research_answer_md",
                title="answer",
                content_uri=str(answer_path),
            )
        ],
        sources=[SourceCandidate(url="https://example.com/a", title="Источник A")],
    )

    text = runs_route._compose_web_research_chat_text(result)

    assert text.startswith("Краткий итог:")
    assert "\n\nДетали:\n" in text
    assert "Источники:" in text


def test_regression_web_research_chat_text_sources_optional_when_absent(tmp_path: Path) -> None:
    answer_path = tmp_path / "web_answer.md"
    answer_path.write_text("Краткий итог: Данные собраны.", encoding="utf-8")

    result = SkillResult(
        what_i_did="Собрал данные.",
        artifacts=[
            ArtifactCandidate(
                type="web_research_answer_md",
                title="answer",
                content_uri=str(answer_path),
            )
        ],
        sources=[],
    )

    text = runs_route._compose_web_research_chat_text(result)

    assert text.startswith("Краткий итог:")
    assert "Источники:" not in text


def test_smoke_noisy_web_answer_rebuilds_to_clean_generic_text(tmp_path: Path) -> None:
    query = "Объясни в двух абзацах, как работает TLS handshake"
    answer_path = tmp_path / "web_answer_dirty.md"
    answer_path.write_text(
        (
            "百度百科: случайный мусор и обрывки текста...\n"
            "###!!!###\n"
            "TLS handshake согласует версии протокола, шифросюиты и параметры сессии.\n"
            "После проверки сертификата стороны выводят общий секрет и переходят к шифрованному каналу."
        ),
        encoding="utf-8",
    )

    result = SkillResult(
        what_i_did="Собрал и сверил источники.",
        artifacts=[
            ArtifactCandidate(
                type="web_research_answer_md",
                title="answer",
                content_uri=str(answer_path),
            )
        ],
        sources=[
            SourceCandidate(url="https://example.org/tls-handshake", title="TLS handshake guide"),
            SourceCandidate(url="https://example.org/tls-certs", title="TLS certificates overview"),
        ],
    )

    composed = runs_route._compose_web_research_chat_text(result)
    clean = runs_route._finalize_chat_user_visible_answer(
        composed,
        user_text=query,
        response_mode="direct_answer",
    )

    assert clean.strip() != ""
    assert "###!!!###" not in clean
    assert "百度" not in clean
    assert re.search(r"[\u4e00-\u9fff]", clean) is None
    assert "Источники:" in clean
    assert "TLS handshake" in clean
    assert "https://example.org/tls-handshake" in clean


@pytest.mark.xfail(
    reason="Known regression: planner defaults to COMPUTER_ACTIONS for complex non-UI requests without plan_hint.",
    strict=False,
)
def test_regression_complex_goal_should_not_default_to_single_computer_actions_step() -> None:
    # Pass criteria:
    # 1) complex analytical request gets decomposition (2+ steps)
    # 2) plan is not reduced to a single COMPUTER_ACTIONS step
    run = {
        "query_text": "подготовь мне план тренировок на неделю чтобы похудеть со 120 кг до 90",
        "meta": {"intent": "ACT"},
    }
    plan = planner.create_plan_for_run(run)
    assert len(plan) >= 2
    assert all(step.get("kind") != "COMPUTER_ACTIONS" for step in plan)


def test_regression_chat_context_keeps_recent_constraints_across_turns(tmp_path: Path) -> None:
    # Pass criteria:
    # 1) recent user constraint survives in assembled context
    # 2) newest user message is appended as final turn
    _init_db(tmp_path)
    project = store.create_project("brain-regressions", [], {})
    run1 = _create_chat_run(project["id"], "Запомни: мне нужен короткий формат ответа.")
    run2 = _create_chat_run(project["id"], "Ок, а что по тренировкам?", parent_run_id=run1["id"])
    run3 = _create_chat_run(project["id"], "Продолжай с учётом прошлого контекста", parent_run_id=run2["id"])

    history = store.list_recent_chat_turns(run3["id"], limit_turns=3)
    messages = build_chat_messages("system", history, "дай следующий шаг")

    user_messages = [item["content"] for item in messages if item["role"] == "user"]
    assert any("короткий формат" in text.lower() for text in user_messages)
    assert messages[-1] == {"role": "user", "content": "дай следующий шаг"}

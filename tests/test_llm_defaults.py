from __future__ import annotations

from core.brain.router import BrainConfig


def test_llm_defaults_local_models(monkeypatch):
    for key in (
        "ASTRA_LLM_LOCAL_CHAT_MODEL",
        "ASTRA_LLM_LOCAL_CHAT_MODEL_FAST",
        "ASTRA_LLM_LOCAL_CHAT_MODEL_COMPLEX",
        "ASTRA_LLM_LOCAL_CODE_MODEL",
        "ASTRA_LLM_FAST_QUERY_MAX_CHARS",
        "ASTRA_LLM_FAST_QUERY_MAX_WORDS",
        "ASTRA_LLM_COMPLEX_QUERY_MIN_CHARS",
        "ASTRA_LLM_COMPLEX_QUERY_MIN_WORDS",
        "ASTRA_LLM_LOCAL_BASE_URL",
        "ASTRA_LLM_CLOUD_MODEL",
        "ASTRA_LLM_CLOUD_BASE_URL",
        "ASTRA_CLOUD_ENABLED",
        "ASTRA_AUTO_CLOUD_ENABLED",
        "OPENAI_API_KEY",
    ):
        monkeypatch.delenv(key, raising=False)

    cfg = BrainConfig.from_env()
    assert cfg.local_chat_model == "qwen2.5:7b-instruct"
    assert cfg.local_chat_fast_model == "qwen2.5:3b-instruct"
    assert cfg.local_chat_complex_model == "qwen2.5:7b-instruct"
    assert cfg.local_fast_query_max_chars == 120
    assert cfg.local_fast_query_max_words == 18
    assert cfg.local_complex_query_min_chars == 260
    assert cfg.local_complex_query_min_words == 45
    assert cfg.local_code_model == "deepseek-coder-v2:16b-lite-instruct-q8_0"
    assert cfg.cloud_enabled is False
    assert cfg.auto_cloud_enabled is False

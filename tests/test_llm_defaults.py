from __future__ import annotations

from core.brain.router import BrainConfig


def test_llm_defaults_no_qwen(monkeypatch):
    for key in (
        "ASTRA_LLM_LOCAL_CHAT_MODEL",
        "ASTRA_LLM_LOCAL_CODE_MODEL",
        "ASTRA_LLM_LOCAL_BASE_URL",
        "ASTRA_LLM_CLOUD_MODEL",
        "ASTRA_LLM_CLOUD_BASE_URL",
        "ASTRA_CLOUD_ENABLED",
        "ASTRA_AUTO_CLOUD_ENABLED",
        "OPENAI_API_KEY",
    ):
        monkeypatch.delenv(key, raising=False)

    cfg = BrainConfig.from_env()
    assert cfg.local_chat_model == "saiga-nemo-12b"
    assert cfg.local_code_model == "deepseek-coder-v2:16b-lite-instruct-q8_0"
    assert "qwen" not in cfg.local_chat_model.lower()
    assert "qwen" not in cfg.local_code_model.lower()
    assert cfg.cloud_enabled is False
    assert cfg.auto_cloud_enabled is False

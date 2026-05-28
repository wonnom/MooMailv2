from __future__ import annotations

from moomail_finance_ai.llm import (
    GeminiLLMClient,
    OpenAILLMClient,
    build_llm_client_from_env,
    load_gemini_config,
    load_openai_config,
)


def test_build_llm_client_from_env_selects_gemini():
    client = build_llm_client_from_env(
        provider="gemini",
        env_file=None,
        env={
            "MOOMAIL_GEMINI_API_KEY": "gemini-key",
            "MOOMAIL_GEMINI_MODEL": "gemini-test",
        },
    )

    assert isinstance(client, GeminiLLMClient)
    assert client.config.model == "gemini-test"


def test_build_llm_client_from_env_selects_openai():
    client = build_llm_client_from_env(
        provider="openai",
        env_file=None,
        env={
            "MOOMAIL_OPENAI_API_KEY": "openai-key",
            "MOOMAIL_OPENAI_MODEL": "gpt-test",
        },
    )

    assert isinstance(client, OpenAILLMClient)
    assert client.config.model == "gpt-test"


def test_llm_config_loaders_accept_legacy_openai_and_google_names():
    gemini = load_gemini_config(env={"GOOGLE_API_KEY": "google-key", "MOOMAIL_GEMINI_MODEL": "gemini-test"})
    openai = load_openai_config(env={"MOOMAIL_LLM_API_KEY": "openai-key", "MOOMAIL_LLM_MODEL": "gpt-test"})

    assert gemini.api_key == "google-key"
    assert openai.api_key == "openai-key"
    assert openai.model == "gpt-test"

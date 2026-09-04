"""Phase 9J: LLM factory selection is centralized and fail-closed."""

from __future__ import annotations

import pytest

from app.core.config import Settings
from app.core.exceptions import ValidationError
from app.services.ai.anthropic_llm import AnthropicLLMProvider
from app.services.ai.gemini_llm import GeminiLLMProvider
from app.services.ai.llm import FakeLLMProvider, get_llm_provider
from app.services.ai.openai_compatible_llm import OpenAICompatibleLLMProvider
from app.services.ai.openai_llm import OpenAILLMProvider


def test_fake_factory_needs_no_key() -> None:
    settings = Settings(_env_file=None, ai_llm_provider="fake")
    provider = get_llm_provider(settings)
    assert isinstance(provider, FakeLLMProvider)
    assert type(provider) is FakeLLMProvider


def test_openai_factory() -> None:
    settings = Settings(
        _env_file=None,
        ai_llm_provider="openai",
        ai_llm_api_key="sk-unit-test-not-a-real-key",
    )
    provider = get_llm_provider(settings)
    assert type(provider) is OpenAILLMProvider
    assert provider.model == "gpt-4o-mini"


def test_anthropic_factory() -> None:
    settings = Settings(
        _env_file=None,
        ai_llm_provider="anthropic",
        ai_llm_model="claude-sonnet-4-6",
        ai_llm_api_key="secret-anthropic-123",
    )
    provider = get_llm_provider(settings)
    assert isinstance(provider, AnthropicLLMProvider)
    assert provider.model == "claude-sonnet-4-6"


def test_gemini_factory() -> None:
    settings = Settings(
        _env_file=None,
        ai_llm_provider="gemini",
        ai_llm_model="gemini-2.0-flash",
        ai_llm_api_key="secret-gemini-123",
    )
    provider = get_llm_provider(settings)
    assert isinstance(provider, GeminiLLMProvider)
    assert provider.model == "gemini-2.0-flash"


def test_openai_compatible_factory() -> None:
    settings = Settings(
        _env_file=None,
        ai_llm_provider="openai_compatible",
        ai_llm_model="qwen-test",
        ai_llm_api_key="secret-qwen-123",
        ai_llm_base_url="https://example.test/compatible-mode/v1",
    )
    provider = get_llm_provider(settings)
    assert isinstance(provider, OpenAICompatibleLLMProvider)
    assert type(provider) is not OpenAILLMProvider
    assert provider.model == "qwen-test"


def test_unknown_provider_fails_closed() -> None:
    with pytest.raises(ValidationError, match="Unsupported LLM provider"):
        get_llm_provider(
            Settings(_env_file=None, ai_llm_provider="fake").model_copy(
                update={"ai_llm_provider": "azure"}
            )
        )


def test_inactive_provider_credentials_are_not_required() -> None:
    settings = Settings(
        _env_file=None,
        ai_llm_provider="openai",
        ai_llm_api_key="sk-unit-test-not-a-real-key",
        ai_llm_base_url="",
    )
    assert settings.ai_llm_provider == "openai"
    provider = get_llm_provider(settings)
    assert type(provider) is OpenAILLMProvider

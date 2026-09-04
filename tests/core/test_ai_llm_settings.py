"""AI-9A LLM settings: fake default; openai requires a key."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.core.config import Settings


def test_default_llm_settings_are_fake() -> None:
    settings = Settings(_env_file=None)
    assert settings.ai_llm_provider == "fake"
    assert settings.ai_llm_model == "gpt-4o-mini"
    assert settings.ai_llm_api_key.get_secret_value() == ""
    assert settings.ai_allow_fake_llm_in_production is False


def test_development_allows_fake_llm() -> None:
    settings = Settings(_env_file=None, app_env="development", ai_llm_provider="fake")
    assert not settings.is_production
    assert settings.ai_llm_provider == "fake"


def test_llm_provider_is_normalized() -> None:
    settings = Settings(_env_file=None, ai_llm_provider=" Fake ")
    assert settings.ai_llm_provider == "fake"


def test_openai_llm_requires_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("AI_LLM_API_KEY", raising=False)
    with pytest.raises(ValidationError, match="AI_LLM_API_KEY"):
        Settings(_env_file=None, ai_llm_provider="openai")


def test_openai_llm_accepted_with_key() -> None:
    settings = Settings(
        _env_file=None,
        ai_llm_provider="openai",
        ai_llm_api_key="sk-unit-test-not-a-real-key",
    )
    assert settings.ai_llm_provider == "openai"
    assert settings.ai_llm_model == "gpt-4o-mini"


def test_llm_api_key_is_not_in_repr() -> None:
    secret = "sk-unit-test-llm-secret-must-not-leak"
    settings = Settings(
        _env_file=None,
        ai_llm_provider="openai",
        ai_llm_api_key=secret,
    )
    dumped = repr(settings)
    assert secret not in dumped


@pytest.mark.parametrize(
    "provider",
    ["anthropic", "gemini", "openai_compatible"],
)
def test_hosted_llm_requires_api_key(provider: str, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("AI_LLM_API_KEY", raising=False)
    kwargs: dict[str, str] = {"ai_llm_provider": provider, "ai_llm_model": "test-model"}
    if provider == "openai_compatible":
        kwargs["ai_llm_base_url"] = "https://example.test/compatible-mode/v1"
    with pytest.raises(ValidationError, match="AI_LLM_API_KEY"):
        Settings(_env_file=None, **kwargs)


def test_compatible_requires_base_url() -> None:
    with pytest.raises(ValidationError, match="AI_LLM_BASE_URL"):
        Settings(
            _env_file=None,
            ai_llm_provider="openai_compatible",
            ai_llm_model="qwen-test",
            ai_llm_api_key="secret-qwen-123",
        )


def test_openai_does_not_require_base_url() -> None:
    settings = Settings(
        _env_file=None,
        ai_llm_provider="openai",
        ai_llm_api_key="sk-unit-test-not-a-real-key",
    )
    assert settings.ai_llm_base_url == ""


def test_fake_needs_no_key_or_base_url() -> None:
    settings = Settings(_env_file=None, ai_llm_provider="fake")
    assert settings.ai_llm_api_key.get_secret_value() == ""
    assert settings.ai_llm_base_url == ""


def test_empty_hosted_model_is_rejected() -> None:
    with pytest.raises(ValidationError, match="AI_LLM_MODEL"):
        Settings(
            _env_file=None,
            ai_llm_provider="anthropic",
            ai_llm_model="   ",
            ai_llm_api_key="secret-anthropic-123",
        )


@pytest.mark.parametrize("provider", ["azure", "qwen", ""])
def test_unknown_llm_provider_is_rejected(provider: str) -> None:
    with pytest.raises(ValidationError, match="AI_LLM_PROVIDER must be"):
        Settings(_env_file=None, ai_llm_provider=provider)


def test_ai_chat_rate_limit_defaults_and_rejects_negative() -> None:
    settings = Settings(_env_file=None)
    assert settings.ai_chat_rate_limit == 20
    assert settings.ai_chat_rate_window_seconds == 60
    with pytest.raises(ValidationError, match="AI_CHAT_RATE_LIMIT"):
        Settings(_env_file=None, ai_chat_rate_limit=-1)


def test_ai10a_reliability_defaults() -> None:
    settings = Settings(_env_file=None)
    assert settings.ai_provider_max_retries == 2
    assert settings.ai_provider_retry_backoff_seconds == 0.2
    assert settings.ai_provider_retry_max_backoff_seconds == 2.0
    assert settings.ai_chat_timeout_seconds == 25.0
    assert settings.ai_telegram_conversation_ttl_seconds == 86_400
    with pytest.raises(ValidationError, match="AI_PROVIDER_MAX_RETRIES"):
        Settings(_env_file=None, ai_provider_max_retries=9)
    with pytest.raises(ValidationError, match="AI_CHAT_TIMEOUT_SECONDS"):
        Settings(_env_file=None, ai_chat_timeout_seconds=0)
    with pytest.raises(ValidationError, match="AI_TELEGRAM_CONVERSATION_TTL_SECONDS"):
        Settings(_env_file=None, ai_telegram_conversation_ttl_seconds=1)

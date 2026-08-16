"""AI-1 embedding settings: fake default; openai requires a key and dim 1536."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from app.core.ai_constants import (
    KB_CHUNK_VECTOR_DIMENSION,
    OPENAI_EMBEDDING_DIMENSION,
)
from app.core.config import Settings


def test_default_embedding_settings_are_fake_matching_column() -> None:
    settings = Settings(_env_file=None)
    assert settings.ai_embedding_provider == "fake"
    assert settings.ai_embedding_dimension == KB_CHUNK_VECTOR_DIMENSION
    assert settings.ai_embedding_dimension == OPENAI_EMBEDDING_DIMENSION
    assert settings.ai_embedding_api_key.get_secret_value() == ""


def test_embedding_provider_is_normalized_to_fake() -> None:
    settings = Settings(_env_file=None, ai_embedding_provider=" Fake ")
    assert settings.ai_embedding_provider == "fake"


def test_openai_provider_is_accepted_with_key() -> None:
    settings = Settings(
        _env_file=None,
        ai_embedding_provider="openai",
        ai_embedding_api_key="sk-unit-test-not-a-real-key",
        ai_embedding_dimension=OPENAI_EMBEDDING_DIMENSION,
    )
    assert settings.ai_embedding_provider == "openai"
    assert settings.ai_embedding_model == "text-embedding-3-small"


def test_openai_provider_requires_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("AI_EMBEDDING_API_KEY", raising=False)
    with pytest.raises(ValidationError, match="AI_EMBEDDING_API_KEY"):
        Settings(_env_file=None, ai_embedding_provider="openai")


def test_openai_provider_rejects_wrong_dimension() -> None:
    with pytest.raises(ValidationError, match="1536"):
        Settings(
            _env_file=None,
            ai_embedding_provider="openai",
            ai_embedding_api_key="sk-unit-test-not-a-real-key",
            ai_embedding_dimension=8,
        )


@pytest.mark.parametrize("provider", ["e5", "http", "azure", ""])
def test_unknown_embedding_provider_is_rejected(provider: str) -> None:
    with pytest.raises(ValidationError, match="AI_EMBEDDING_PROVIDER must be"):
        Settings(_env_file=None, ai_embedding_provider=provider)


@pytest.mark.parametrize("dimension", [0, -1, 4097])
def test_embedding_dimension_out_of_range_is_rejected(dimension: int) -> None:
    with pytest.raises(ValidationError, match="AI_EMBEDDING_DIMENSION"):
        Settings(_env_file=None, ai_embedding_dimension=dimension)


def test_embedding_dimension_bounds_are_accepted() -> None:
    low = Settings(_env_file=None, ai_embedding_dimension=1)
    high = Settings(_env_file=None, ai_embedding_dimension=4096)
    assert low.ai_embedding_dimension == 1
    assert high.ai_embedding_dimension == 4096


def test_embedding_api_key_is_not_in_repr() -> None:
    secret = "sk-unit-test-secret-must-not-leak"
    settings = Settings(
        _env_file=None,
        ai_embedding_provider="openai",
        ai_embedding_api_key=secret,
    )
    dumped = repr(settings)
    assert secret not in dumped
    assert "**********" in dumped or "SecretStr" in dumped


def test_openai_api_key_env_alias(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-from-openai-alias")
    settings = Settings(
        _env_file=None,
        ai_embedding_provider="openai",
        ai_embedding_dimension=OPENAI_EMBEDDING_DIMENSION,
    )
    assert settings.ai_embedding_api_key.get_secret_value() == "sk-from-openai-alias"

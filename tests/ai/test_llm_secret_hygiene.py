"""Phase 9J: API keys never appear in errors, logs, or reprs."""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from app.core.config import Settings
from app.services.ai.anthropic_llm import AnthropicLLMProvider
from app.services.ai.gemini_llm import GeminiLLMProvider
from app.services.ai.openai_compatible_llm import OpenAICompatibleLLMProvider
from app.services.ai.openai_http import raise_as_app_error
from app.services.ai.openai_llm import OpenAILLMProvider

SECRETS = (
    "secret-openai-123",
    "secret-anthropic-123",
    "secret-gemini-123",
    "secret-qwen-123",
)


def _assert_clean(text: str) -> None:
    for secret in SECRETS:
        assert secret not in text


def test_settings_repr_hides_llm_key() -> None:
    settings = Settings(
        _env_file=None,
        ai_llm_provider="openai_compatible",
        ai_llm_model="qwen-test",
        ai_llm_api_key="secret-qwen-123",
        ai_llm_base_url="https://example.test/compatible-mode/v1",
    )
    _assert_clean(repr(settings))


@pytest.mark.parametrize(
    ("status", "body"),
    [
        (401, {"error": {"message": "bad secret-openai-123"}}),
        (403, {"error": {"message": "no secret-anthropic-123"}}),
        (400, {"error": {"code": "AccessDenied.Unpurchased", "message": "secret-qwen-123"}}),
        (500, {"error": {"message": "secret-gemini-123 boom"}}),
    ],
)
def test_normalized_errors_omit_secrets(status: int, body: dict[str, Any]) -> None:
    with pytest.raises(Exception) as captured:
        raise_as_app_error(httpx.Response(status, json=body), kind="llm")
    _assert_clean(str(captured.value))
    _assert_clean(repr(captured.value))


def test_provider_reprs_omit_secrets() -> None:
    providers = [
        OpenAILLMProvider(api_key="secret-openai-123"),
        AnthropicLLMProvider(api_key="secret-anthropic-123", model="claude-test"),
        GeminiLLMProvider(api_key="secret-gemini-123", model="gemini-test"),
        OpenAICompatibleLLMProvider(
            api_key="secret-qwen-123",
            model="qwen-test",
            base_url="https://example.test/compatible-mode/v1",
        ),
    ]
    for provider in providers:
        _assert_clean(repr(provider))


async def test_generate_errors_omit_secrets_and_prompts(
    caplog: pytest.LogCaptureFixture,
) -> None:
    async def boom(_url: str, _headers: dict[str, str], payload: dict[str, Any]) -> dict[str, Any]:
        raise_as_app_error(
            httpx.Response(401, json={"error": {"message": "secret-openai-123"}}),
            kind="llm",
        )
        raise AssertionError("unreachable")

    question = "UNIQUE_SECRET_PROMPT_SHOULD_NOT_APPEAR"
    provider = OpenAILLMProvider(api_key="secret-openai-123", http_post=boom)
    with caplog.at_level("INFO", logger="app.kb.llm"):
        with pytest.raises(Exception) as captured:
            await provider.generate(system_prompt="sys", user_prompt=question)
    _assert_clean(str(captured.value))
    combined = " ".join(record.getMessage() for record in caplog.records)
    _assert_clean(combined)
    assert question not in combined
    assert "Authorization" not in combined
    assert "Bearer" not in combined

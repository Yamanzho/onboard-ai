"""Anthropic Messages adapter. HTTP is mocked — no live network."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import httpx
import pytest

from app.core.ai_constants import ANTHROPIC_API_VERSION, DEFAULT_LLM_MAX_OUTPUT_TOKENS
from app.core.exceptions import ServiceUnavailableError, ValidationError
from app.services.ai.anthropic_llm import AnthropicLLMProvider
from app.services.ai.openai_http import raise_as_app_error

ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"


async def test_anthropic_request_and_text_extraction() -> None:
    captured: dict[str, Any] = {}

    async def post(url: str, headers: dict[str, str], payload: dict[str, Any]) -> dict[str, Any]:
        captured["url"] = url
        captured["headers"] = headers
        captured["payload"] = payload
        return {
            "content": [
                {"type": "text", "text": "Policy is [S1]."},
                {"type": "tool_use", "id": "x", "name": "noop"},
            ]
        }

    provider = AnthropicLLMProvider(
        api_key="secret-anthropic-123",
        model="claude-sonnet-4-6",
        http_post=post,
    )
    result = await provider.generate(system_prompt="sys", user_prompt="How is leave?")
    assert captured["url"] == ANTHROPIC_URL
    assert captured["headers"]["x-api-key"] == "secret-anthropic-123"
    assert captured["headers"]["anthropic-version"] == ANTHROPIC_API_VERSION
    assert captured["payload"]["model"] == "claude-sonnet-4-6"
    assert captured["payload"]["max_tokens"] == DEFAULT_LLM_MAX_OUTPUT_TOKENS
    assert captured["payload"]["system"] == "sys"
    assert captured["payload"]["messages"] == [{"role": "user", "content": "How is leave?"}]
    assert result.no_answer is False
    assert "[S1]" in result.text


async def test_anthropic_malformed_body() -> None:
    async def empty(
        _url: str, _headers: dict[str, str], _payload: dict[str, Any]
    ) -> dict[str, Any]:
        return {"content": []}

    provider = AnthropicLLMProvider(
        api_key="secret-anthropic-123",
        model="claude-sonnet-4-6",
        http_post=empty,
    )
    with pytest.raises(ValidationError, match="invalid completion") as captured:
        await provider.generate(system_prompt="sys", user_prompt="hello")
    assert "secret-anthropic-123" not in str(captured.value)


async def test_anthropic_auth_rate_limit() -> None:
    with pytest.raises(ValidationError, match="credentials"):
        raise_as_app_error(httpx.Response(401, json={"error": {}}), kind="llm")
    with pytest.raises(ServiceUnavailableError, match="unavailable"):
        raise_as_app_error(httpx.Response(429, json={"error": {}}), kind="llm")


async def test_anthropic_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
    class _TimeoutClient:
        def __init__(self, *args: object, **kwargs: object) -> None:
            pass

        async def __aenter__(self) -> _TimeoutClient:
            return self

        async def __aexit__(self, *args: object) -> bool:
            return False

        async def post(self, *args: object, **kwargs: object) -> httpx.Response:
            raise httpx.TimeoutException("timed out")

    monkeypatch.setattr("app.services.ai.openai_http.httpx.AsyncClient", _TimeoutClient)
    monkeypatch.setattr("app.services.ai.openai_http.retry_sleep", AsyncMock())
    provider = AnthropicLLMProvider(
        api_key="secret-anthropic-123",
        model="claude-sonnet-4-6",
    )
    with pytest.raises(ServiceUnavailableError, match="timed out") as captured:
        await provider.generate(system_prompt="sys", user_prompt="hello")
    assert "secret-anthropic-123" not in str(captured.value)
    assert "hello" not in str(captured.value)


def test_anthropic_requires_api_key() -> None:
    with pytest.raises(ValidationError, match="API key"):
        AnthropicLLMProvider(api_key="  ", model="claude-sonnet-4-6")

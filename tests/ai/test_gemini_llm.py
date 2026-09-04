"""Gemini generateContent adapter. HTTP is mocked — no live network."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import httpx
import pytest

from app.core.ai_constants import DEFAULT_LLM_MAX_OUTPUT_TOKENS
from app.core.exceptions import ServiceUnavailableError, ValidationError
from app.services.ai.gemini_llm import GeminiLLMProvider
from app.services.ai.openai_http import raise_as_app_error

GEMINI_URL = (
    "https://generativelanguage.googleapis.com/v1beta/models/"
    "gemini-2.0-flash:generateContent"
)


async def test_gemini_request_and_text_extraction() -> None:
    captured: dict[str, Any] = {}

    async def post(url: str, headers: dict[str, str], payload: dict[str, Any]) -> dict[str, Any]:
        captured["url"] = url
        captured["headers"] = headers
        captured["payload"] = payload
        return {
            "candidates": [
                {
                    "content": {
                        "parts": [{"text": "Policy is "}, {"text": "[S1]."}],
                    }
                }
            ]
        }

    provider = GeminiLLMProvider(
        api_key="secret-gemini-123",
        model="gemini-2.0-flash",
        http_post=post,
    )
    result = await provider.generate(system_prompt="sys", user_prompt="How is leave?")
    assert captured["url"] == GEMINI_URL
    assert captured["headers"]["x-goog-api-key"] == "secret-gemini-123"
    assert "key=" not in captured["url"]
    assert captured["payload"]["system_instruction"] == {"parts": [{"text": "sys"}]}
    assert captured["payload"]["contents"] == [
        {"role": "user", "parts": [{"text": "How is leave?"}]}
    ]
    assert captured["payload"]["generationConfig"]["maxOutputTokens"] == (
        DEFAULT_LLM_MAX_OUTPUT_TOKENS
    )
    assert result.text == "Policy is [S1]."


async def test_gemini_malformed_body() -> None:
    async def empty(
        _url: str, _headers: dict[str, str], _payload: dict[str, Any]
    ) -> dict[str, Any]:
        return {"candidates": []}

    provider = GeminiLLMProvider(
        api_key="secret-gemini-123",
        model="gemini-2.0-flash",
        http_post=empty,
    )
    with pytest.raises(ValidationError, match="invalid completion") as captured:
        await provider.generate(system_prompt="sys", user_prompt="hello")
    assert "secret-gemini-123" not in str(captured.value)


async def test_gemini_auth_rate_limit() -> None:
    with pytest.raises(ValidationError, match="credentials"):
        raise_as_app_error(httpx.Response(401, json={"error": {}}), kind="llm")
    with pytest.raises(ServiceUnavailableError, match="unavailable"):
        raise_as_app_error(httpx.Response(429, json={"error": {}}), kind="llm")


async def test_gemini_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
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
    provider = GeminiLLMProvider(api_key="secret-gemini-123", model="gemini-2.0-flash")
    with pytest.raises(ServiceUnavailableError, match="timed out") as captured:
        await provider.generate(system_prompt="sys", user_prompt="hello")
    assert "secret-gemini-123" not in str(captured.value)
    assert "hello" not in str(captured.value)


def test_gemini_requires_api_key() -> None:
    with pytest.raises(ValidationError, match="API key"):
        GeminiLLMProvider(api_key="", model="gemini-2.0-flash")


def test_gemini_repr_omits_secret() -> None:
    provider = GeminiLLMProvider(api_key="secret-gemini-123", model="gemini-2.0-flash")
    assert "secret-gemini-123" not in repr(provider)

"""OpenAI-compatible / Qwen adapter. HTTP is mocked — no live network."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import httpx
import pytest

from app.core.exceptions import ServiceUnavailableError, ValidationError
from app.services.ai.openai_compatible_llm import OpenAICompatibleLLMProvider
from app.services.ai.openai_http import raise_as_app_error

COMPAT_ROOT = "https://example.test/compatible-mode/v1"
COMPAT_URL = f"{COMPAT_ROOT}/chat/completions"


async def test_compatible_posts_chat_completions() -> None:
    captured: dict[str, Any] = {}

    async def post(url: str, headers: dict[str, str], payload: dict[str, Any]) -> dict[str, Any]:
        captured["url"] = url
        captured["headers"] = headers
        captured["payload"] = payload
        return {"choices": [{"message": {"content": "Leave is [S1]."}}]}

    provider = OpenAICompatibleLLMProvider(
        api_key="secret-qwen-123",
        model="qwen-test",
        base_url=COMPAT_ROOT,
        http_post=post,
    )
    result = await provider.generate(system_prompt="sys", user_prompt="How is leave?")
    assert captured["url"] == COMPAT_URL
    assert captured["headers"]["Authorization"] == "Bearer secret-qwen-123"
    assert captured["payload"]["model"] == "qwen-test"
    assert captured["payload"]["messages"][0] == {"role": "system", "content": "sys"}
    assert captured["payload"]["messages"][1] == {"role": "user", "content": "How is leave?"}
    assert result.no_answer is False
    assert "[S1]" in result.text


async def test_compatible_does_not_double_slash_or_invent_v1() -> None:
    captured: dict[str, Any] = {}

    async def post(url: str, headers: dict[str, str], payload: dict[str, Any]) -> dict[str, Any]:
        captured["url"] = url
        return {"choices": [{"message": {"content": "ok"}}]}

    provider = OpenAICompatibleLLMProvider(
        api_key="secret-qwen-123",
        model="qwen-test",
        base_url=f"{COMPAT_ROOT}/",
        http_post=post,
    )
    await provider.generate(system_prompt="sys", user_prompt="q")
    assert captured["url"] == COMPAT_URL
    assert "//chat/completions" not in captured["url"]


async def test_compatible_keeps_explicit_chat_completions_path() -> None:
    captured: dict[str, Any] = {}

    async def post(url: str, headers: dict[str, str], payload: dict[str, Any]) -> dict[str, Any]:
        captured["url"] = url
        return {"choices": [{"message": {"content": "ok"}}]}

    provider = OpenAICompatibleLLMProvider(
        api_key="secret-qwen-123",
        model="qwen-test",
        base_url=COMPAT_URL,
        http_post=post,
    )
    await provider.generate(system_prompt="sys", user_prompt="q")
    assert captured["url"] == COMPAT_URL


async def test_compatible_malformed_response() -> None:
    async def empty(
        _url: str, _headers: dict[str, str], _payload: dict[str, Any]
    ) -> dict[str, Any]:
        return {"choices": []}

    provider = OpenAICompatibleLLMProvider(
        api_key="secret-qwen-123",
        model="qwen-test",
        base_url=COMPAT_ROOT,
        http_post=empty,
    )
    with pytest.raises(ValidationError, match="invalid completion") as captured:
        await provider.generate(system_prompt="sys", user_prompt="hello")
    assert "secret-qwen-123" not in str(captured.value)


async def test_compatible_auth_and_permission_errors() -> None:
    with pytest.raises(ValidationError, match="credentials"):
        raise_as_app_error(httpx.Response(401, json={"error": {}}), kind="llm")
    with pytest.raises(ValidationError, match="denied access"):
        raise_as_app_error(
            httpx.Response(
                403,
                json={"error": {"code": "AccessDenied.Unpurchased", "message": "pay"}},
            ),
            kind="llm",
        )
    with pytest.raises(ValidationError, match="denied access") as captured:
        raise_as_app_error(
            httpx.Response(
                400,
                json={"error": {"code": "AccessDenied.Unpurchased", "message": "pay"}},
            ),
            kind="llm",
        )
    assert "secret-qwen-123" not in str(captured.value)
    assert "AccessDenied.Unpurchased" not in str(captured.value)


async def test_compatible_timeout(monkeypatch: pytest.MonkeyPatch) -> None:
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
    provider = OpenAICompatibleLLMProvider(
        api_key="secret-qwen-123",
        model="qwen-test",
        base_url=COMPAT_ROOT,
    )
    with pytest.raises(ServiceUnavailableError, match="timed out") as captured:
        await provider.generate(system_prompt="sys", user_prompt="hello")
    assert "secret-qwen-123" not in str(captured.value)
    assert "hello" not in str(captured.value)


def test_compatible_requires_base_url_and_key() -> None:
    with pytest.raises(ValidationError, match="API key"):
        OpenAICompatibleLLMProvider(
            api_key="  ",
            model="qwen-test",
            base_url=COMPAT_ROOT,
        )
    with pytest.raises(ValidationError, match="AI_LLM_BASE_URL"):
        OpenAICompatibleLLMProvider(
            api_key="secret-qwen-123",
            model="qwen-test",
            base_url="",
        )

"""OpenAILLMProvider HTTP via httpx, mocked — no live network."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import httpx
import pytest

from app.core.ai_constants import OPENAI_LLM_MODEL
from app.core.exceptions import ServiceUnavailableError, ValidationError
from app.services.ai.openai_llm import OpenAILLMProvider


async def _ok_post(_url: str, headers: dict[str, str], payload: dict[str, Any]) -> dict[str, Any]:
    assert payload["model"] == OPENAI_LLM_MODEL
    assert payload["temperature"] == 0
    assert headers["Authorization"].startswith("Bearer ")
    assert payload["messages"][0]["role"] == "system"
    assert payload["messages"][1]["role"] == "user"
    return {
        "choices": [
            {"message": {"role": "assistant", "content": "Leave is [S1]."}}
        ]
    }


@pytest.fixture
def provider() -> OpenAILLMProvider:
    return OpenAILLMProvider(
        api_key="sk-unit-test-not-a-real-key",
        http_post=_ok_post,
    )


async def test_openai_llm_returns_completion(provider: OpenAILLMProvider) -> None:
    result = await provider.generate(system_prompt="sys", user_prompt="How is leave?")
    assert result.no_answer is False
    assert "[S1]" in result.text
    assert provider.model == OPENAI_LLM_MODEL


async def test_openai_llm_requires_api_key() -> None:
    with pytest.raises(ValidationError, match="API key"):
        OpenAILLMProvider(api_key="  ")


async def test_openai_llm_rejected_credentials() -> None:
    from app.services.ai.openai_llm import _decode_openai_llm_response

    with pytest.raises(ValidationError, match="credentials"):
        _decode_openai_llm_response(httpx.Response(401, json={"error": {}}))
    with pytest.raises(ValidationError, match="credentials"):
        _decode_openai_llm_response(httpx.Response(403, json={"error": {}}))


async def test_openai_llm_rate_limit_and_server_errors() -> None:
    from app.services.ai.openai_llm import _decode_openai_llm_response

    for status in (429, 500, 502, 503, 504):
        with pytest.raises(ServiceUnavailableError, match="unavailable"):
            _decode_openai_llm_response(httpx.Response(status, json={"error": {}}))


async def test_openai_llm_timeout_is_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
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
    provider = OpenAILLMProvider(api_key="sk-unit-test-not-a-real-key")
    with pytest.raises(ServiceUnavailableError, match="timed out") as captured:
        await provider.generate(system_prompt="sys", user_prompt="hello")
    assert "sk-unit-test-not-a-real-key" not in str(captured.value)
    assert "hello" not in str(captured.value)


async def test_openai_llm_malformed_response_is_safe_failure() -> None:
    from app.services.ai.openai_llm import _decode_openai_llm_response

    with pytest.raises(ServiceUnavailableError, match="invalid JSON"):
        _decode_openai_llm_response(httpx.Response(200, text="not-json"))

    async def _bad_shape(
        _url: str, _headers: dict[str, str], _payload: dict[str, Any]
    ) -> dict[str, Any]:
        return {"choices": []}

    provider = OpenAILLMProvider(
        api_key="sk-unit-test-not-a-real-key",
        http_post=_bad_shape,
    )
    with pytest.raises(ValidationError) as captured:
        await provider.generate(system_prompt="sys", user_prompt="hello")
    assert "sk-unit-test-not-a-real-key" not in str(captured.value)
    assert "hello" not in str(captured.value)


async def test_openai_llm_does_not_log_key_or_prompts(
    caplog: pytest.LogCaptureFixture,
) -> None:
    secret = "sk-unit-test-secret-must-not-leak"
    question = "UNIQUE_LLM_QUESTION_SHOULD_NOT_APPEAR"

    async def post(_url: str, _headers: dict[str, str], payload: dict[str, Any]) -> dict[str, Any]:
        assert payload["messages"][1]["content"] == question
        return {"choices": [{"message": {"content": "NO_ANSWER"}}]}

    provider = OpenAILLMProvider(api_key=secret, http_post=post)
    with caplog.at_level("INFO", logger="app.kb.llm"):
        result = await provider.generate(system_prompt="sys", user_prompt=question)
    combined = " ".join(record.getMessage() for record in caplog.records)
    assert secret not in combined
    assert question not in combined
    assert result.no_answer is True
    assert secret not in repr(provider)

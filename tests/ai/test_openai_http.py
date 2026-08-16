"""AI-10A OpenAI HTTP: bounded retries, classification, no secret leakage."""

from __future__ import annotations

from unittest.mock import AsyncMock

import httpx
import pytest

from app.core.exceptions import ServiceUnavailableError, ValidationError
from app.services.ai.metrics import counter_value, reset_ai_metrics_for_tests
from app.services.ai.openai_http import (
    ProviderFailure,
    classify_openai_response,
    post_openai_json,
    raise_as_app_error,
)


@pytest.fixture(autouse=True)
def _reset_metrics() -> None:
    reset_ai_metrics_for_tests()
    yield
    reset_ai_metrics_for_tests()


def test_classify_credentials_are_not_retryable() -> None:
    for status in (401, 403):
        with pytest.raises(ProviderFailure) as captured:
            classify_openai_response(
                httpx.Response(status, json={"error": {"message": "sk-secret"}}),
                kind="embedding",
            )
        assert captured.value.retryable is False
        assert captured.value.error_class == "credentials"
        assert "sk-secret" not in str(captured.value)


def test_classify_transient_statuses() -> None:
    for status, error_class in (
        (429, "rate_limit"),
        (500, "server_error"),
        (502, "server_error"),
        (503, "server_error"),
        (504, "server_error"),
    ):
        with pytest.raises(ProviderFailure) as captured:
            classify_openai_response(httpx.Response(status, json={"error": {}}), kind="llm")
        assert captured.value.retryable is True
        assert captured.value.error_class == error_class


def test_classify_invalid_json_is_not_retryable() -> None:
    with pytest.raises(ProviderFailure) as captured:
        classify_openai_response(httpx.Response(200, text="not-json"), kind="llm")
    assert captured.value.retryable is False
    assert captured.value.error_class == "invalid_json"


def test_raise_as_app_error_maps_classes() -> None:
    with pytest.raises(ValidationError, match="credentials"):
        raise_as_app_error(httpx.Response(401, json={}), kind="embedding")
    with pytest.raises(ServiceUnavailableError, match="unavailable"):
        raise_as_app_error(httpx.Response(503, json={}), kind="llm")


@pytest.mark.asyncio
async def test_retries_then_succeeds(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = {"n": 0}
    sleeps: list[float] = []

    class _Client:
        def __init__(self, *args: object, **kwargs: object) -> None:
            pass

        async def __aenter__(self) -> _Client:
            return self

        async def __aexit__(self, *args: object) -> bool:
            return False

        async def post(self, *args: object, **kwargs: object) -> httpx.Response:
            calls["n"] += 1
            if calls["n"] < 3:
                return httpx.Response(503, json={"error": {}})
            return httpx.Response(200, json={"ok": True})

    async def _sleep(seconds: float) -> None:
        sleeps.append(seconds)

    monkeypatch.setattr("app.services.ai.openai_http.httpx.AsyncClient", _Client)
    monkeypatch.setattr("app.services.ai.openai_http.retry_sleep", _sleep)
    body = await post_openai_json(
        "https://api.openai.com/v1/chat/completions",
        {"Authorization": "Bearer sk-unit-test-not-a-real-key"},
        {"model": "gpt-4o-mini"},
        timeout=1.0,
        kind="llm",
    )
    assert body == {"ok": True}
    assert calls["n"] == 3
    assert sleeps == [0.2, 0.4]
    assert counter_value("ai_retries", provider="openai", operation="llm", result="error") == 2


@pytest.mark.asyncio
async def test_does_not_retry_401(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = {"n": 0}

    class _Client:
        def __init__(self, *args: object, **kwargs: object) -> None:
            pass

        async def __aenter__(self) -> _Client:
            return self

        async def __aexit__(self, *args: object) -> bool:
            return False

        async def post(self, *args: object, **kwargs: object) -> httpx.Response:
            calls["n"] += 1
            return httpx.Response(401, json={"error": {"message": "sk-leak"}})

    monkeypatch.setattr("app.services.ai.openai_http.httpx.AsyncClient", _Client)
    monkeypatch.setattr("app.services.ai.openai_http.retry_sleep", AsyncMock())
    with pytest.raises(ProviderFailure) as captured:
        await post_openai_json(
            "https://api.openai.com/v1/embeddings",
            {"Authorization": "Bearer sk-unit-test-not-a-real-key"},
            {"input": ["secret-question"]},
            timeout=1.0,
            kind="embedding",
        )
    assert calls["n"] == 1
    assert captured.value.error_class == "credentials"
    assert "sk-leak" not in str(captured.value)
    assert "secret-question" not in str(captured.value)


@pytest.mark.asyncio
async def test_retry_after_is_capped(monkeypatch: pytest.MonkeyPatch) -> None:
    sleeps: list[float] = []
    calls = {"n": 0}

    class _Client:
        def __init__(self, *args: object, **kwargs: object) -> None:
            pass

        async def __aenter__(self) -> _Client:
            return self

        async def __aexit__(self, *args: object) -> bool:
            return False

        async def post(self, *args: object, **kwargs: object) -> httpx.Response:
            calls["n"] += 1
            return httpx.Response(
                429,
                json={"error": {}},
                headers={"Retry-After": "120"},
            )

    async def _sleep(seconds: float) -> None:
        sleeps.append(seconds)

    monkeypatch.setattr("app.services.ai.openai_http.httpx.AsyncClient", _Client)
    monkeypatch.setattr("app.services.ai.openai_http.retry_sleep", _sleep)
    with pytest.raises(ProviderFailure) as captured:
        await post_openai_json(
            "https://api.openai.com/v1/chat/completions",
            {"Authorization": "Bearer sk-unit-test-not-a-real-key"},
            {"model": "gpt-4o-mini"},
            timeout=1.0,
            kind="llm",
        )
    assert captured.value.error_class == "rate_limit"
    assert calls["n"] == 3
    assert sleeps == [2.0, 2.0]


@pytest.mark.asyncio
async def test_timeout_retries_then_fails(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = {"n": 0}

    class _Client:
        def __init__(self, *args: object, **kwargs: object) -> None:
            pass

        async def __aenter__(self) -> _Client:
            return self

        async def __aexit__(self, *args: object) -> bool:
            return False

        async def post(self, *args: object, **kwargs: object) -> httpx.Response:
            calls["n"] += 1
            raise httpx.TimeoutException("timed out")

    monkeypatch.setattr("app.services.ai.openai_http.httpx.AsyncClient", _Client)
    monkeypatch.setattr("app.services.ai.openai_http.retry_sleep", AsyncMock())
    with pytest.raises(ProviderFailure) as captured:
        await post_openai_json(
            "https://api.openai.com/v1/embeddings",
            {"Authorization": "Bearer sk-unit-test-not-a-real-key"},
            {"input": ["hello"]},
            timeout=1.0,
            kind="embedding",
        )
    assert captured.value.error_class == "timeout"
    assert calls["n"] == 3
    assert "sk-unit-test-not-a-real-key" not in str(captured.value)


@pytest.mark.asyncio
async def test_logs_do_not_contain_secrets(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    class _Client:
        def __init__(self, *args: object, **kwargs: object) -> None:
            pass

        async def __aenter__(self) -> _Client:
            return self

        async def __aexit__(self, *args: object) -> bool:
            return False

        async def post(self, *args: object, **kwargs: object) -> httpx.Response:
            return httpx.Response(
                500,
                json={"error": {"message": "sk-live-secret", "prompt": "UNIQUE_PROMPT"}},
            )

    monkeypatch.setattr("app.services.ai.openai_http.httpx.AsyncClient", _Client)
    monkeypatch.setattr("app.services.ai.openai_http.retry_sleep", AsyncMock())
    with caplog.at_level("INFO"):
        with pytest.raises(ProviderFailure):
            await post_openai_json(
                "https://api.openai.com/v1/chat/completions",
                {"Authorization": "Bearer sk-live-secret"},
                {"messages": [{"role": "user", "content": "UNIQUE_QUESTION"}]},
                timeout=1.0,
                kind="llm",
            )
    combined = " ".join(record.getMessage() for record in caplog.records)
    assert "sk-live-secret" not in combined
    assert "UNIQUE_PROMPT" not in combined
    assert "UNIQUE_QUESTION" not in combined
    assert "Authorization" not in combined
    assert "error_class=server_error" in combined

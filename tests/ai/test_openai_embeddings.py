"""OpenAIEmbeddingProvider: HTTP via httpx, mocked — no live network, no LLM."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import httpx
import pytest

from app.core.ai_constants import OPENAI_EMBEDDING_DIMENSION, OPENAI_EMBEDDING_MODEL
from app.core.config import Settings
from app.core.exceptions import ServiceUnavailableError, ValidationError
from app.services.ai.embeddings import FakeEmbeddingProvider, get_embedding_provider
from app.services.ai.openai_embeddings import OpenAIEmbeddingProvider


def _vector(fill: float = 0.01) -> list[float]:
    return [fill] * OPENAI_EMBEDDING_DIMENSION


async def _ok_post(_url: str, headers: dict[str, str], payload: dict[str, Any]) -> dict[str, Any]:
    texts = payload["input"]
    assert payload["model"] == OPENAI_EMBEDDING_MODEL
    assert payload["dimensions"] == OPENAI_EMBEDDING_DIMENSION
    assert headers["Authorization"].startswith("Bearer ")
    return {
        "data": [
            {"index": index, "embedding": _vector(0.02)}
            for index in range(len(texts))
        ]
    }


@pytest.fixture
def provider() -> OpenAIEmbeddingProvider:
    return OpenAIEmbeddingProvider(
        api_key="sk-unit-test-not-a-real-key",
        http_post=_ok_post,
    )


async def test_openai_batch_preserves_order_and_dimension(
    provider: OpenAIEmbeddingProvider,
) -> None:
    batch = await provider.embed_batch(["alpha", "beta"])
    assert len(batch) == 2
    assert all(len(vector) == OPENAI_EMBEDDING_DIMENSION for vector in batch)
    single = await provider.embed("alpha")
    assert len(single) == OPENAI_EMBEDDING_DIMENSION
    assert provider.model == OPENAI_EMBEDDING_MODEL


async def test_openai_empty_batch_is_empty(provider: OpenAIEmbeddingProvider) -> None:
    assert await provider.embed_batch([]) == []


async def test_openai_rejects_empty_text(provider: OpenAIEmbeddingProvider) -> None:
    with pytest.raises(ValidationError, match="must not be empty"):
        await provider.embed("  ")


async def test_openai_requires_api_key() -> None:
    with pytest.raises(ValidationError, match="API key"):
        OpenAIEmbeddingProvider(api_key="  ")


async def test_openai_rejects_wrong_constructor_dimension() -> None:
    with pytest.raises(ValidationError, match="1536"):
        OpenAIEmbeddingProvider(api_key="sk-unit-test-not-a-real-key", dimension=8)


async def test_openai_sorts_by_index() -> None:
    async def shuffled(
        _url: str,
        _headers: dict[str, str],
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        return {
            "data": [
                {"index": 1, "embedding": _vector(0.2)},
                {"index": 0, "embedding": _vector(0.1)},
            ]
        }

    provider = OpenAIEmbeddingProvider(
        api_key="sk-unit-test-not-a-real-key",
        http_post=shuffled,
    )
    batch = await provider.embed_batch(["first", "second"])
    assert batch[0][0] == pytest.approx(0.1)
    assert batch[1][0] == pytest.approx(0.2)


async def test_openai_dimension_mismatch_in_response() -> None:
    async def short(_url: str, _headers: dict[str, str], payload: dict[str, Any]) -> dict[str, Any]:
        return {"data": [{"index": 0, "embedding": [0.1, 0.2]}]}

    provider = OpenAIEmbeddingProvider(
        api_key="sk-unit-test-not-a-real-key",
        http_post=short,
    )
    with pytest.raises(ValidationError, match="dimension mismatch"):
        await provider.embed("x")


async def test_openai_unavailable_on_http_status() -> None:
    from app.services.ai.openai_embeddings import _decode_openai_response

    with pytest.raises(ServiceUnavailableError, match="unavailable"):
        _decode_openai_response(httpx.Response(503, json={"error": {"message": "busy"}}))


async def test_openai_rejected_credentials() -> None:
    from app.services.ai.openai_embeddings import _decode_openai_response

    with pytest.raises(ValidationError, match="credentials"):
        _decode_openai_response(httpx.Response(401, json={"error": {}}))
    with pytest.raises(ValidationError, match="credentials"):
        _decode_openai_response(httpx.Response(403, json={"error": {}}))


async def test_openai_rate_limit_and_server_errors() -> None:
    from app.services.ai.openai_embeddings import _decode_openai_response

    for status in (429, 500, 502, 503, 504):
        with pytest.raises(ServiceUnavailableError, match="unavailable"):
            _decode_openai_response(httpx.Response(status, json={"error": {}}))


async def test_openai_timeout_is_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    class _TimeoutClient:
        def __init__(self, *args: object, **kwargs: object) -> None:
            pass

        async def __aenter__(self) -> _TimeoutClient:
            return self

        async def __aexit__(self, *args: object) -> bool:
            return False

        async def post(self, *args: object, **kwargs: object) -> httpx.Response:
            raise httpx.TimeoutException("timed out")

    monkeypatch.setattr(
        "app.services.ai.openai_http.httpx.AsyncClient",
        _TimeoutClient,
    )
    monkeypatch.setattr("app.services.ai.openai_http.retry_sleep", AsyncMock())
    provider = OpenAIEmbeddingProvider(api_key="sk-unit-test-not-a-real-key")
    with pytest.raises(ServiceUnavailableError, match="timed out") as captured:
        await provider.embed("hello")
    assert "sk-unit-test-not-a-real-key" not in str(captured.value)
    assert "hello" not in str(captured.value)


async def test_openai_malformed_response_is_safe_failure() -> None:
    from app.services.ai.openai_embeddings import _decode_openai_response

    with pytest.raises(ServiceUnavailableError, match="invalid JSON"):
        _decode_openai_response(httpx.Response(200, text="not-json"))

    async def _bad_shape(
        _url: str, _headers: dict[str, str], _payload: dict[str, Any]
    ) -> dict[str, Any]:
        return {"data": "nope"}

    provider = OpenAIEmbeddingProvider(
        api_key="sk-unit-test-not-a-real-key",
        http_post=_bad_shape,
    )
    with pytest.raises(ValidationError) as captured:
        await provider.embed("hello")
    message = str(captured.value)
    assert "sk-unit-test-not-a-real-key" not in message
    assert "hello" not in message


async def test_openai_does_not_log_key_or_input(
    caplog: pytest.LogCaptureFixture,
) -> None:
    secret = "sk-unit-test-secret-must-not-leak"
    query = "UNIQUE_EMBED_QUERY_SHOULD_NOT_APPEAR"

    async def post(_url: str, _headers: dict[str, str], payload: dict[str, Any]) -> dict[str, Any]:
        assert payload["input"] == [query]
        return {"data": [{"index": 0, "embedding": _vector()}]}

    provider = OpenAIEmbeddingProvider(api_key=secret, http_post=post)
    with caplog.at_level("INFO", logger="app.kb.embed"):
        await provider.embed(query)
    combined = " ".join(record.getMessage() for record in caplog.records)
    assert secret not in combined
    assert query not in combined
    assert "model=" in combined
    assert "result=success" in combined


async def test_factory_returns_openai_from_settings() -> None:
    settings = Settings(
        _env_file=None,
        ai_embedding_provider="openai",
        ai_embedding_api_key="sk-unit-test-not-a-real-key",
        ai_embedding_dimension=OPENAI_EMBEDDING_DIMENSION,
    )
    provider = get_embedding_provider(settings)
    assert isinstance(provider, OpenAIEmbeddingProvider)
    assert provider.dimension == OPENAI_EMBEDDING_DIMENSION
    assert not isinstance(provider, FakeEmbeddingProvider)

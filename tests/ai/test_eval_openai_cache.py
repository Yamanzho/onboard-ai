"""OpenAI evaluation path is mocked in CI. No live network, no API key required."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from app.core.ai_constants import OPENAI_EMBEDDING_DIMENSION, OPENAI_EMBEDDING_MODEL
from app.core.exceptions import ValidationError
from app.services.ai.evaluation import (
    LIVE_OPENAI_ENV,
    CachedEmbeddingProvider,
    live_openai_enabled,
)
from app.services.ai.openai_embeddings import OpenAIEmbeddingProvider


def _vector(fill: float) -> list[float]:
    return [fill] * OPENAI_EMBEDDING_DIMENSION


async def test_openai_eval_uses_mocked_http_and_cache(tmp_path: Path) -> None:
    calls = {"count": 0}

    async def _post(_url: str, headers: dict[str, str], payload: dict[str, Any]) -> dict[str, Any]:
        calls["count"] += 1
        assert headers["Authorization"].startswith("Bearer ")
        assert "sk-unit-test-not-a-real-key" in headers["Authorization"]
        texts = payload["input"]
        return {
            "data": [
                {"index": index, "embedding": _vector(0.01 * (index + 1))}
                for index in range(len(texts))
            ]
        }

    inner = OpenAIEmbeddingProvider(
        api_key="sk-unit-test-not-a-real-key",
        http_post=_post,
    )
    cache_path = tmp_path / "openai.json"
    cached = CachedEmbeddingProvider(
        inner,
        cache_path,
        model=OPENAI_EMBEDDING_MODEL,
        allow_network=True,
    )
    first = await cached.embed_batch(["one", "two"])
    assert len(first) == 2
    assert calls["count"] == 1
    again = await cached.embed_batch(["one", "two"])
    assert again == first
    assert calls["count"] == 1

    cold = CachedEmbeddingProvider(
        inner,
        cache_path,
        model=OPENAI_EMBEDDING_MODEL,
        allow_network=False,
    )
    replayed = await cold.embed_batch(["two", "one"])
    assert replayed[0] == first[1]
    assert replayed[1] == first[0]
    assert calls["count"] == 1


async def test_openai_eval_cache_miss_without_network(tmp_path: Path) -> None:
    async def _must_not_run(_url: str, _headers: dict[str, str], _payload: dict[str, Any]):
        raise AssertionError("live OpenAI must not be called in CI")

    inner = OpenAIEmbeddingProvider(
        api_key="sk-unit-test-not-a-real-key",
        http_post=_must_not_run,
    )
    cached = CachedEmbeddingProvider(
        inner,
        tmp_path / "empty.json",
        model=OPENAI_EMBEDDING_MODEL,
        allow_network=False,
    )
    with pytest.raises(ValidationError, match="cache miss"):
        await cached.embed("employee question")


def test_live_openai_is_opt_in(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(LIVE_OPENAI_ENV, raising=False)
    assert live_openai_enabled() is False


def test_cache_rejects_secret_fields(tmp_path: Path) -> None:
    from app.services.ai.embeddings import FakeEmbeddingProvider

    path = tmp_path / "poison.json"
    path.write_text(
        '{"model":"fake-test","dimension":8,"api_key":"sk-leak","vectors":{}}',
        encoding="utf-8",
    )
    with pytest.raises(ValidationError, match="secrets"):
        CachedEmbeddingProvider(
            FakeEmbeddingProvider(dimension=8),
            path,
            model="fake-test",
            allow_network=False,
        )


async def test_cache_persists_purpose_without_secrets_or_text(tmp_path: Path) -> None:
    import json

    from app.services.ai.embeddings import FakeEmbeddingProvider
    from app.services.ai.evaluation import CACHE_PURPOSE, cache_key

    inner = FakeEmbeddingProvider(dimension=8)
    path = tmp_path / "ok.json"
    cached = CachedEmbeddingProvider(
        inner, path, model="fake-test", allow_network=True
    )
    await cached.embed("synthetic evaluation only")
    raw = json.loads(path.read_text(encoding="utf-8"))
    assert raw["purpose"] == CACHE_PURPOSE
    assert raw["not_a_kb_index"] is True
    assert "api_key" not in raw
    assert "texts" not in raw
    blob = path.read_text(encoding="utf-8")
    assert "synthetic evaluation only" not in blob
    assert "sk-" not in blob
    assert cache_key("fake-test", "synthetic evaluation only") in raw["vectors"]

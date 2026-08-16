"""FakeEmbeddingProvider: deterministic, in-process, no network."""

from __future__ import annotations

from collections.abc import Sequence

import pytest

from app.core.exceptions import ValidationError
from app.services.ai.embeddings import (
    DEFAULT_FAKE_EMBEDDING_DIMENSION,
    EmbeddingProvider,
    FakeEmbeddingProvider,
    get_embedding_provider,
)


@pytest.fixture
def provider() -> FakeEmbeddingProvider:
    return FakeEmbeddingProvider()


async def test_embeddings_are_deterministic(provider: FakeEmbeddingProvider) -> None:
    first = await provider.embed("Как оформить отпуск?")
    second = await provider.embed("Как оформить отпуск?")
    assert first == second
    assert len(first) == DEFAULT_FAKE_EMBEDDING_DIMENSION


async def test_batch_embeddings_match_single_calls(provider: FakeEmbeddingProvider) -> None:
    texts = ["alpha", "beta"]
    batch = await provider.embed_batch(texts)
    assert batch == [
        await provider.embed("alpha"),
        await provider.embed("beta"),
    ]


async def test_batch_embeddings_preserve_order(provider: FakeEmbeddingProvider) -> None:
    texts = ["first", "second", "third"]
    batch = await provider.embed_batch(texts)
    assert [len(vector) for vector in batch] == [provider.dimension] * 3
    assert batch[0] != batch[1]
    assert batch[1] != batch[2]


async def test_empty_sequence_returns_empty_list(provider: FakeEmbeddingProvider) -> None:
    assert await provider.embed_batch([]) == []


async def test_empty_text_is_rejected(provider: FakeEmbeddingProvider) -> None:
    with pytest.raises(ValidationError, match="must not be empty"):
        await provider.embed("")
    with pytest.raises(ValidationError, match="must not be empty"):
        await provider.embed("   ")
    with pytest.raises(ValidationError, match="must not be empty"):
        await provider.embed_batch(["ok", ""])


async def test_embed_batch_rejects_a_single_string(provider: FakeEmbeddingProvider) -> None:
    with pytest.raises(ValidationError, match="sequence of strings"):
        await provider.embed_batch("not-a-batch")  # type: ignore[arg-type]


@pytest.mark.parametrize("dimension", [1, 4, 8, 32])
async def test_dimension_is_honored(dimension: int) -> None:
    provider = FakeEmbeddingProvider(dimension=dimension)
    vector = await provider.embed("dimension-check")
    assert provider.dimension == dimension
    assert len(vector) == dimension


@pytest.mark.parametrize("dimension", [0, -1, 4097, True, 8.5])
def test_invalid_dimension_is_rejected(dimension: object) -> None:
    with pytest.raises(ValidationError, match="embedding dimension"):
        FakeEmbeddingProvider(dimension=dimension)  # type: ignore[arg-type]


async def test_multiple_texts_are_stable_and_distinct(provider: FakeEmbeddingProvider) -> None:
    texts = ["RU отпуск", "EN vacation", "KK демалыс"]
    first = await provider.embed_batch(texts)
    second = await provider.embed_batch(texts)
    assert first == second
    assert first[0] != first[1]
    assert first[1] != first[2]
    assert all(len(vector) == provider.dimension for vector in first)


async def test_provider_interface_is_structural() -> None:
    provider: EmbeddingProvider = FakeEmbeddingProvider(dimension=4)
    assert isinstance(provider, EmbeddingProvider)
    assert provider.dimension == 4
    vector = await provider.embed("protocol")
    batch = await provider.embed_batch(["a", "b"])
    assert len(vector) == 4
    assert len(batch) == 2


async def test_alternate_implementation_satisfies_protocol() -> None:
    class StubProvider:
        dimension = 2

        async def embed(self, text: str) -> list[float]:
            vectors = await self.embed_batch((text,))
            return vectors[0]

        async def embed_batch(self, texts: Sequence[str]) -> list[list[float]]:
            return [[1.0, 0.0] for _ in texts]

    stub: EmbeddingProvider = StubProvider()
    assert isinstance(stub, EmbeddingProvider)
    assert await stub.embed("x") == [1.0, 0.0]


async def test_factory_returns_fake_provider_from_settings() -> None:
    from app.core.config import Settings

    settings = Settings(_env_file=None, ai_embedding_provider="fake", ai_embedding_dimension=4)
    provider = get_embedding_provider(settings)
    assert isinstance(provider, FakeEmbeddingProvider)
    assert isinstance(provider, EmbeddingProvider)
    assert provider.dimension == 4
    vector = await provider.embed("factory")
    assert len(vector) == 4

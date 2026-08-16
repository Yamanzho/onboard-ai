"""Provider-independent embedding interface.

Dev/CI: ``FakeEmbeddingProvider`` (in-process, no network).
Production hosted: ``OpenAIEmbeddingProvider`` (text-embedding-3-small).

Vector storage is not an ACL authority; this module only turns text into floats.
API keys must never be logged.
"""

from __future__ import annotations

import hashlib
import math
from collections.abc import Sequence
from typing import Protocol, runtime_checkable

from app.core.ai_constants import (
    KB_CHUNK_VECTOR_DIMENSION,
    SUPPORTED_EMBEDDING_PROVIDERS,
)
from app.core.config import Settings, get_settings
from app.core.exceptions import ValidationError

DEFAULT_FAKE_EMBEDDING_DIMENSION = KB_CHUNK_VECTOR_DIMENSION
MIN_EMBEDDING_DIMENSION = 1
MAX_EMBEDDING_DIMENSION = 4096


@runtime_checkable
class EmbeddingProvider(Protocol):
    """Contract for turning text into a fixed-width float vector.

    Implementations must be deterministic for a given input. They must not be
    treated as an authorization source.
    """

    @property
    def dimension(self) -> int:
        """Width of every vector this provider returns."""
        ...

    async def embed(self, text: str) -> list[float]:
        """Embed a single non-empty text."""
        ...

    async def embed_batch(self, texts: Sequence[str]) -> list[list[float]]:
        """Embed texts in order. An empty sequence returns an empty list."""
        ...


def _validate_dimension(dimension: int) -> int:
    if isinstance(dimension, bool) or not isinstance(dimension, int):
        raise ValidationError("embedding dimension must be an integer")
    if dimension < MIN_EMBEDDING_DIMENSION or dimension > MAX_EMBEDDING_DIMENSION:
        raise ValidationError(
            "embedding dimension must be between "
            f"{MIN_EMBEDDING_DIMENSION} and {MAX_EMBEDDING_DIMENSION}"
        )
    return dimension


def _require_non_empty_text(text: object) -> str:
    if not isinstance(text, str):
        raise ValidationError("text must be a string")
    if not text.strip():
        raise ValidationError("text must not be empty")
    return text


def _hash_units(text: str, dimension: int) -> list[float]:
    values: list[float] = []
    counter = 0
    encoded = text.encode("utf-8")
    while len(values) < dimension:
        digest = hashlib.sha256(counter.to_bytes(4, "big") + b"\0" + encoded).digest()
        for byte in digest:
            values.append((byte / 127.5) - 1.0)
            if len(values) >= dimension:
                break
        counter += 1
    return values


def _l2_normalize(values: list[float]) -> list[float]:
    norm = math.sqrt(sum(component * component for component in values))
    if norm == 0.0:
        equal = 1.0 / math.sqrt(len(values))
        return [equal] * len(values)
    return [component / norm for component in values]


class FakeEmbeddingProvider:
    """Deterministic in-process embeddings for tests and local development.

    The same UTF-8 input always yields the same vector. There is no network
    and no secret. Vectors are L2-normalized so later cosine retrieval can
    treat them as direction-only.
    """

    def __init__(self, *, dimension: int = DEFAULT_FAKE_EMBEDDING_DIMENSION) -> None:
        self._dimension = _validate_dimension(dimension)

    @property
    def dimension(self) -> int:
        return self._dimension

    @property
    def model(self) -> str:
        return "fake"

    async def embed(self, text: str) -> list[float]:
        vectors = await self.embed_batch((text,))
        return vectors[0]

    async def embed_batch(self, texts: Sequence[str]) -> list[list[float]]:
        if isinstance(texts, str | bytes):
            raise ValidationError("texts must be a sequence of strings, not a single string")
        if not isinstance(texts, Sequence):
            raise ValidationError("texts must be a sequence of strings")
        vectors: list[list[float]] = []
        for text in texts:
            _require_non_empty_text(text)
            vector = _l2_normalize(_hash_units(text, self._dimension))
            if len(vector) != self._dimension:
                raise ValidationError(
                    "embedding dimension mismatch: expected "
                    f"{self._dimension}, got {len(vector)}"
                )
            vectors.append(vector)
        return vectors


def get_embedding_provider(settings: Settings | None = None) -> EmbeddingProvider:
    """Return the configured embedding provider. Unknown providers fail closed."""
    resolved = settings or get_settings()
    provider = resolved.ai_embedding_provider.strip().lower()
    if provider not in SUPPORTED_EMBEDDING_PROVIDERS:
        raise ValidationError(
            f"Unsupported embedding provider {resolved.ai_embedding_provider!r}"
        )
    if provider == "fake":
        return FakeEmbeddingProvider(dimension=resolved.ai_embedding_dimension)
    if provider == "openai":
        from app.services.ai.openai_embeddings import OpenAIEmbeddingProvider

        return OpenAIEmbeddingProvider(
            api_key=resolved.ai_embedding_api_key.get_secret_value(),
            model=resolved.ai_embedding_model,
            dimension=resolved.ai_embedding_dimension,
            timeout_seconds=resolved.ai_embedding_timeout_seconds,
        )
    raise ValidationError(
        f"Unsupported embedding provider {resolved.ai_embedding_provider!r}"
    )

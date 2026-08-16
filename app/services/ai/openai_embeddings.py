"""OpenAI text-embedding-3-small provider. No LLM. Key never logged."""

from __future__ import annotations

import logging
import time
from collections.abc import Awaitable, Callable, Sequence
from typing import Any

import httpx

from app.core.ai_constants import (
    DEFAULT_EMBEDDING_TIMEOUT_SECONDS,
    OPENAI_EMBEDDING_DIMENSION,
    OPENAI_EMBEDDING_MODEL,
    OPENAI_EMBEDDINGS_URL,
)
from app.core.exceptions import ServiceUnavailableError, ValidationError
from app.core.request_id import request_id_log_value
from app.services.ai.embeddings import _require_non_empty_text
from app.services.ai.openai_http import (
    ProviderFailure,
    post_openai_json,
    raise_as_app_error,
)

logger = logging.getLogger("app.kb.embed")

_MAX_BATCH = 2048

HttpPost = Callable[[str, dict[str, str], dict[str, Any]], Awaitable[dict[str, Any]]]


class OpenAIEmbeddingProvider:
    """Hosted embeddings via the OpenAI HTTP API (httpx, no SDK).

    Vectors are not an authorization source. The API key must never appear in
    logs, exception messages, or chunk metadata.
    """

    def __init__(
        self,
        *,
        api_key: str,
        model: str = OPENAI_EMBEDDING_MODEL,
        dimension: int = OPENAI_EMBEDDING_DIMENSION,
        timeout_seconds: float = DEFAULT_EMBEDDING_TIMEOUT_SECONDS,
        base_url: str = OPENAI_EMBEDDINGS_URL,
        http_post: HttpPost | None = None,
    ) -> None:
        key = api_key.strip()
        if not key:
            raise ValidationError("OpenAI embedding API key is required")
        if dimension != OPENAI_EMBEDDING_DIMENSION:
            raise ValidationError(
                "OpenAI embedding dimension must be "
                f"{OPENAI_EMBEDDING_DIMENSION}, got {dimension}"
            )
        self._api_key = key
        self._model = model.strip() or OPENAI_EMBEDDING_MODEL
        self._dimension = dimension
        self._timeout = timeout_seconds
        self._base_url = base_url
        self._http_post = http_post

    @property
    def dimension(self) -> int:
        return self._dimension

    @property
    def model(self) -> str:
        return self._model

    async def embed(self, text: str) -> list[float]:
        vectors = await self.embed_batch((text,))
        return vectors[0]

    async def embed_batch(self, texts: Sequence[str]) -> list[list[float]]:
        if isinstance(texts, str | bytes):
            raise ValidationError("texts must be a sequence of strings, not a single string")
        if not isinstance(texts, Sequence):
            raise ValidationError("texts must be a sequence of strings")
        if not texts:
            return []
        if len(texts) > _MAX_BATCH:
            raise ValidationError(f"embedding batch must have at most {_MAX_BATCH} texts")
        payload_texts = [_require_non_empty_text(text) for text in texts]

        started = time.perf_counter()
        try:
            body = await self._post(
                {
                    "model": self._model,
                    "input": payload_texts,
                    "dimensions": self._dimension,
                }
            )
        except (ValidationError, ServiceUnavailableError):
            logger.info(
                "kb_embed_openai request_id=%s model=%s batch_size=%s dimension=%s "
                "result=error duration_ms=%.1f",
                request_id_log_value(),
                self._model,
                len(payload_texts),
                self._dimension,
                (time.perf_counter() - started) * 1000,
            )
            raise

        vectors = _parse_embedding_response(
            body,
            expected=len(payload_texts),
            dimension=self._dimension,
        )
        logger.info(
            "kb_embed_openai request_id=%s model=%s batch_size=%s dimension=%s "
            "result=success duration_ms=%.1f",
            request_id_log_value(),
            self._model,
            len(payload_texts),
            self._dimension,
            (time.perf_counter() - started) * 1000,
        )
        return vectors

    async def _post(self, payload: dict[str, Any]) -> dict[str, Any]:
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        if self._http_post is not None:
            return await self._http_post(self._base_url, headers, payload)
        try:
            return await post_openai_json(
                self._base_url,
                headers,
                payload,
                timeout=self._timeout,
                kind="embedding",
            )
        except ProviderFailure as exc:
            exc.reraise_app()
            raise AssertionError("unreachable") from exc


def _decode_openai_response(response: httpx.Response) -> dict[str, Any]:
    return raise_as_app_error(response, kind="embedding")


def _parse_embedding_response(
    body: dict[str, Any],
    *,
    expected: int,
    dimension: int,
) -> list[list[float]]:
    rows = body.get("data")
    if not isinstance(rows, list) or len(rows) != expected:
        raise ValidationError("embedding batch size does not match chunks")
    ordered: list[tuple[int, list[float]]] = []
    for row in rows:
        if not isinstance(row, dict):
            raise ValidationError("embedding provider returned an invalid vector")
        index = row.get("index")
        embedding = row.get("embedding")
        if not isinstance(index, int) or isinstance(index, bool):
            raise ValidationError("embedding provider returned an invalid vector")
        if not isinstance(embedding, list) or len(embedding) != dimension:
            raise ValidationError(
                "embedding dimension mismatch: expected "
                f"{dimension}, got {len(embedding) if isinstance(embedding, list) else 0}"
            )
        vector: list[float] = []
        for component in embedding:
            if isinstance(component, bool) or not isinstance(component, int | float):
                raise ValidationError("embedding provider returned an invalid vector")
            vector.append(float(component))
        ordered.append((index, vector))
    ordered.sort(key=lambda item: item[0])
    if [item[0] for item in ordered] != list(range(expected)):
        raise ValidationError("embedding provider returned an invalid vector")
    return [item[1] for item in ordered]

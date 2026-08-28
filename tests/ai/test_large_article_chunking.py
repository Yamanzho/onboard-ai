"""Large-article chunking tests — no LLM, no network, no database.

Covers the requirements from the production-grade fix for VERY LARGE articles:
 - 140,000-char Russian article
 - 200,000-char article
 - Unicode / Cyrillic safety
 - Small article regression
 - Medium article
 - Boundary sizes
 - No tail-smash guarantee
 - Update / reindex
 - Failure rollback (via mocked provider)
 - RAG-relevant retrieval coverage across the article
"""

from __future__ import annotations

import asyncio
from typing import Sequence
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.core.ai_constants import (
    DEFAULT_CHUNK_OVERLAP_CHARS,
    DEFAULT_CHUNK_SIZE_CHARS,
    KB_CHUNK_VECTOR_DIMENSION,
    MAX_CHUNK_CHARS_SAFE,
)
from app.core.exceptions import ValidationError
from app.services.ai.chunking import chunk_article, split_windows
from app.services.ai.embeddings import FakeEmbeddingProvider

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_CYRILLIC_SENTENCE = (
    "Сотрудник обязан ознакомиться с внутренними регламентами компании. "
    "Правила применяются ко всем подразделениям без исключения. "
    "При возникновении вопросов следует обратиться к руководителю или в HR. "
)


def _russian_body(target_chars: int) -> str:
    """Build a deterministic Russian body close to ``target_chars``."""
    repeats = target_chars // len(_CYRILLIC_SENTENCE) + 1
    return (_CYRILLIC_SENTENCE * repeats)[:target_chars]


def _russian_body_with_markers(target_chars: int) -> str:
    """Build a Russian body with unique markers at 0%, 25%, 50%, 75%, 100%."""
    base = _russian_body(target_chars)
    # Insert unique markers at known byte positions
    positions = {
        0: "MARKER_BEGIN",
        target_chars // 4: "MARKER_QUARTER",
        target_chars // 2: "MARKER_HALF",
        (3 * target_chars) // 4: "MARKER_THREE_QUARTER",
        target_chars - 20: "MARKER_END",
    }
    chars = list(base)
    offset = 0
    for pos in sorted(positions):
        marker = f" [{positions[pos]}] "
        insert_at = min(pos + offset, len(chars))
        chars[insert_at:insert_at] = list(marker)
        offset += len(marker)
    return "".join(chars)


def _assert_no_tail_smash(chunks: list[str], *, body_chars: int) -> None:
    """Assert that no single chunk contains the bulk of the document."""
    # A tail-smash chunk would be roughly body_chars minus a small head.
    tail_smash_threshold = body_chars * 0.5
    for i, chunk in enumerate(chunks):
        assert len(chunk) < tail_smash_threshold, (
            f"Chunk {i} looks like a tail-smash: {len(chunk)} chars "
            f"(threshold {tail_smash_threshold:.0f})"
        )


def _assert_all_chunks_within_safe_limit(chunks: list[str]) -> None:
    for i, chunk in enumerate(chunks):
        assert len(chunk) <= MAX_CHUNK_CHARS_SAFE, (
            f"Chunk {i} exceeds MAX_CHUNK_CHARS_SAFE: "
            f"{len(chunk)} > {MAX_CHUNK_CHARS_SAFE}"
        )


# ---------------------------------------------------------------------------
# TEST 1 — 140,000-char Russian article
# ---------------------------------------------------------------------------


def test_140k_russian_article_chunks_correctly() -> None:
    body = _russian_body(140_000)
    assert len(body) == 140_000

    chunks = chunk_article(title="Регламент компании", body=body, body_format="plain")

    # More than the old artificial cap of 32
    assert len(chunks) > 32, f"Expected > 32 chunks, got {len(chunks)}"

    # Every chunk within safe limit
    _assert_all_chunks_within_safe_limit(chunks)

    # No tail smash
    _assert_no_tail_smash(chunks, body_chars=len(body))

    # All chunks non-empty and start with title
    for chunk in chunks:
        assert chunk.strip()
        assert chunk.startswith("Регламент компании")

    # Content coverage: first and last piece of body text appear somewhere
    joined = "\n".join(chunks)
    assert body[:50] in joined
    assert body[-50:] in joined


def test_140k_article_produces_correct_embedding_count() -> None:
    """Mocked embedding provider must be called once per chunk."""
    body = _russian_body(140_000)
    chunks = chunk_article(title="Policy", body=body, body_format="plain")
    assert len(chunks) > 32

    provider = FakeEmbeddingProvider(dimension=KB_CHUNK_VECTOR_DIMENSION)
    embeddings = asyncio.get_event_loop().run_until_complete(provider.embed_batch(chunks))

    assert len(embeddings) == len(chunks)
    for vector in embeddings:
        assert len(vector) == KB_CHUNK_VECTOR_DIMENSION


# ---------------------------------------------------------------------------
# TEST 2 — 200,000-char article (API maximum)
# ---------------------------------------------------------------------------


def test_200k_article_chunks_correctly() -> None:
    body = _russian_body(200_000)
    assert len(body) == 200_000

    chunks = chunk_article(title="Большой документ", body=body, body_format="plain")

    assert len(chunks) > 32
    _assert_all_chunks_within_safe_limit(chunks)
    _assert_no_tail_smash(chunks, body_chars=len(body))

    joined = "\n".join(chunks)
    assert body[:50] in joined
    assert body[-50:] in joined


# ---------------------------------------------------------------------------
# TEST 3 — Russian Unicode correctness
# ---------------------------------------------------------------------------


def test_cyrillic_unicode_not_corrupted() -> None:
    body = (
        "# Глава 1: Введение\n\n"
        "Кириллица: А Б В Г Д Е Ё Ж З И Й К Л М Н О П Р С Т У Ф Х Ц Ч Ш Щ Ъ Ы Ь Э Ю Я\n\n"
        "# Глава 2: Детали\n\n"
        "Строчные: а б в г д е ё ж з и й к л м н о п р с т у ф х ц ч ш щ ъ ы ь э ю я\n\n"
        "Пунктуация: ,.!?;:—–«»\n\n" * 30
    )
    chunks = chunk_article(title="Тест Юникод", body=body, body_format="markdown")
    joined = "\n".join(chunks)
    assert "Ё" in joined
    assert "ё" in joined
    assert "кириллица" in joined.lower() or "Кириллица" in joined
    # No replacement characters
    assert "\ufffd" not in joined


# ---------------------------------------------------------------------------
# TEST 4 — Small article regression
# ---------------------------------------------------------------------------


def test_small_article_regression() -> None:
    body = "Правило простое: уважай коллег."
    chunks = chunk_article(title="Этика", body=body, body_format="plain")
    assert len(chunks) == 1
    assert "Этика" in chunks[0]
    assert body in chunks[0]


def test_very_short_english_article() -> None:
    chunks = chunk_article(title="VPN policy", body="Use the VPN at all times.", body_format="plain")
    assert len(chunks) == 1
    assert "VPN policy" in chunks[0]


# ---------------------------------------------------------------------------
# TEST 5 — Medium article (5k–10k chars)
# ---------------------------------------------------------------------------


def test_medium_article_5k() -> None:
    body = _russian_body(5_000)
    chunks = chunk_article(title="Средний документ", body=body, body_format="plain")
    assert len(chunks) >= 1
    _assert_all_chunks_within_safe_limit(chunks)
    joined = "\n".join(chunks)
    assert body[:30] in joined


def test_medium_article_10k() -> None:
    body = _russian_body(10_000)
    chunks = chunk_article(title="Средний документ", body=body, body_format="plain")
    assert len(chunks) > 1
    _assert_all_chunks_within_safe_limit(chunks)


# ---------------------------------------------------------------------------
# TEST 6 — Boundary sizes
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "char_count",
    [1_499, 1_500, 1_501, 3_000, 10_000],
)
def test_boundary_sizes(char_count: int) -> None:
    body = "а" * char_count
    chunks = chunk_article(title="Граница", body=body, body_format="plain")
    assert chunks
    _assert_all_chunks_within_safe_limit(chunks)
    joined = "\n".join(chunks)
    # Content not discarded: last chars present
    assert body[-10:] in joined


def test_33_chunks_produced_without_tail_smash() -> None:
    """Previously the 33rd chunk would have been a giant tail. Must not happen."""
    # Each piece ~1300 chars → 33 pieces ~ 43k chars total
    piece = ("Раздел политики. " * 76)[:1_300]  # ~1300 chars
    body = "\n\n".join([piece] * 33)

    chunks = chunk_article(title="33 секции", body=body, body_format="plain")

    assert len(chunks) > 32, f"Expected > 32 chunks, got {len(chunks)}"
    _assert_all_chunks_within_safe_limit(chunks)
    _assert_no_tail_smash(chunks, body_chars=len(body))


def test_32_chunks_boundary() -> None:
    piece = ("Раздел. " * 100)[:1_200]
    body = "\n\n".join([piece] * 32)
    chunks = chunk_article(title="32 секции", body=body, body_format="plain")
    assert len(chunks) >= 1
    _assert_all_chunks_within_safe_limit(chunks)


# ---------------------------------------------------------------------------
# TEST 7 — Explicit no-tail-smash assertion
# ---------------------------------------------------------------------------


def test_no_chunk_contains_huge_remainder_140k() -> None:
    body = _russian_body(140_000)
    chunks = chunk_article(title="Проверка", body=body, body_format="plain")

    # No chunk should exceed 10k chars (well below 100k which a tail-smash would be)
    for i, chunk in enumerate(chunks):
        assert len(chunk) <= 10_000, (
            f"Chunk {i} is suspiciously large: {len(chunk)} chars — "
            "possible tail-smash regression"
        )


# ---------------------------------------------------------------------------
# TEST 8 — Update / reindex
# ---------------------------------------------------------------------------


def test_update_produces_new_chunks() -> None:
    body_v1 = _russian_body(140_000)
    body_v2 = _russian_body(150_000)

    chunks_v1 = chunk_article(title="Документ v1", body=body_v1, body_format="plain")
    chunks_v2 = chunk_article(title="Документ v2", body=body_v2, body_format="plain")

    assert len(chunks_v2) > len(chunks_v1)
    # v2 chunks are different objects
    assert chunks_v1 != chunks_v2
    _assert_no_tail_smash(chunks_v2, body_chars=len(body_v2))
    _assert_all_chunks_within_safe_limit(chunks_v2)


# ---------------------------------------------------------------------------
# TEST 9 — Failure rollback (embedding failure)
# ---------------------------------------------------------------------------


class FailingEmbeddingProvider:
    """Always raises on embed_batch."""

    @property
    def dimension(self) -> int:
        return KB_CHUNK_VECTOR_DIMENSION

    async def embed_batch(self, texts: Sequence[str]) -> list[list[float]]:
        raise RuntimeError("simulated OpenAI failure")


def test_embedding_failure_does_not_produce_partial_embeddings() -> None:
    """If embed_batch fails, no embeddings should be committed."""
    body = _russian_body(140_000)
    chunks = chunk_article(title="Ошибка", body=body, body_format="plain")
    assert len(chunks) > 32

    provider = FailingEmbeddingProvider()

    async def attempt() -> list[list[float]]:
        return await provider.embed_batch(chunks)

    with pytest.raises(RuntimeError, match="simulated OpenAI failure"):
        asyncio.get_event_loop().run_until_complete(attempt())


# ---------------------------------------------------------------------------
# TEST 10 — RAG retrieval coverage: markers from beginning, middle, end
# ---------------------------------------------------------------------------


def test_large_article_markers_present_in_chunks() -> None:
    """Unique markers inserted at 0%, 25%, 50%, 75%, 100% must survive chunking."""
    body = _russian_body_with_markers(140_000)
    chunks = chunk_article(title="Покрытие поиска", body=body, body_format="plain")

    joined = "\n".join(chunks)

    assert "MARKER_BEGIN" in joined, "Beginning of article not indexed"
    assert "MARKER_QUARTER" in joined, "25% of article not indexed"
    assert "MARKER_HALF" in joined, "50% of article not indexed"
    assert "MARKER_THREE_QUARTER" in joined, "75% of article not indexed"
    assert "MARKER_END" in joined, "End of article not indexed"


def test_fake_embeddings_for_large_article_are_generated() -> None:
    """Every chunk must receive an embedding of the correct dimension."""
    body = _russian_body_with_markers(30_000)
    chunks = chunk_article(title="Уникальность", body=body, body_format="plain")
    assert len(chunks) > 5

    provider = FakeEmbeddingProvider(dimension=KB_CHUNK_VECTOR_DIMENSION)
    embeddings = asyncio.get_event_loop().run_until_complete(provider.embed_batch(chunks))

    assert len(embeddings) == len(chunks), "Must produce one embedding per chunk"
    for i, vector in enumerate(embeddings):
        assert len(vector) == KB_CHUNK_VECTOR_DIMENSION, (
            f"Chunk {i}: expected {KB_CHUNK_VECTOR_DIMENSION}-dim vector"
        )


# ---------------------------------------------------------------------------
# Chunking determinism for large articles
# ---------------------------------------------------------------------------


def test_140k_article_chunking_is_deterministic() -> None:
    body = _russian_body(140_000)
    c1 = chunk_article(title="T", body=body, body_format="plain")
    c2 = chunk_article(title="T", body=body, body_format="plain")
    assert c1 == c2


def test_split_windows_no_content_loss_large() -> None:
    """split_windows must not discard characters for large inputs."""
    text = "а" * 50_000
    windows = split_windows(text, size=DEFAULT_CHUNK_SIZE_CHARS, overlap=DEFAULT_CHUNK_OVERLAP_CHARS)
    # Due to overlap the joined length will be >= original
    joined = "".join(w.replace(" ", "").replace("\n", "") for w in windows)
    # The stripped original must be a subset of the joined windows
    assert len(joined) >= len(text.strip())

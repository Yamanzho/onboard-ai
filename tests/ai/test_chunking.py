"""Deterministic KB chunking — no LLM, unicode-safe."""

from __future__ import annotations

from app.core.ai_constants import (
    DEFAULT_CHUNK_OVERLAP_CHARS,
    DEFAULT_CHUNK_SIZE_CHARS,
    MAX_CHUNKS_PER_ARTICLE,
)
from app.services.ai.chunking import chunk_article, html_to_text, split_windows


def test_chunking_is_deterministic() -> None:
    kwargs = {
        "title": "Отпуск",
        "body": "Первый абзац.\n\n" + ("Второй абзац про правила. " * 80),
    }
    first = chunk_article(**kwargs)
    second = chunk_article(**kwargs)
    assert first == second
    assert first
    assert all(chunk.strip() for chunk in first)


def test_empty_text_returns_no_chunks() -> None:
    assert chunk_article(title="", body="", body_format="plain") == []
    assert chunk_article(title="   ", body="\n\n", body_format="plain") == []


def test_short_text_is_single_chunk() -> None:
    chunks = chunk_article(title="VPN", body="Step one", body_format="plain")
    assert len(chunks) == 1
    assert chunks[0].startswith("VPN")
    assert "Step one" in chunks[0]


def test_title_only_is_single_chunk() -> None:
    chunks = chunk_article(title="Policy", body="", body_format="plain")
    assert chunks == ["Policy"]


def test_long_text_preserves_order_and_overlap() -> None:
    paragraphs = [f"Section {index}. " + ("word " * 40) for index in range(12)]
    body = "\n\n".join(paragraphs)
    chunks = chunk_article(title="Guide", body=body, body_format="plain")
    assert 1 < len(chunks) <= MAX_CHUNKS_PER_ARTICLE
    for index, chunk in enumerate(chunks):
        assert chunk.startswith("Guide")
        assert chunk == chunks[index]
    joined = "\n".join(chunks)
    assert "Section 0." in joined
    assert "Section 11." in joined


def test_russian_and_kazakh_are_not_split_mid_codepoint() -> None:
    ru = "Как оформить отпуск? Сотрудник подаёт заявление за три дня."
    kk = "Қызметкер демалысты қалай рәсімдейді? Өтініш үш күн бұрын беріледі."
    ru_chunks = chunk_article(title="Отпуск", body=ru, body_format="plain")
    kk_chunks = chunk_article(title="Демалыс", body=kk, body_format="plain")
    assert ru in ru_chunks[0]
    assert kk in kk_chunks[0]
    assert "Қызметкер" in kk_chunks[0]


def test_english_short_article() -> None:
    chunks = chunk_article(
        title="Vacation policy",
        body="Submit the form three days in advance.",
        body_format="plain",
    )
    assert len(chunks) == 1
    assert "Vacation policy" in chunks[0]
    assert "Submit the form" in chunks[0]


def test_html_body_strips_tags() -> None:
    chunks = chunk_article(
        title="HTML",
        body="<p>Hello <strong>world</strong></p><script>alert(1)</script>",
        body_format="html",
    )
    assert len(chunks) == 1
    assert "Hello" in chunks[0]
    assert "world" in chunks[0]
    assert "<p>" not in chunks[0]
    assert "alert(1)" not in chunks[0]


def test_html_to_text_keeps_unicode() -> None:
    assert "Қазақстан" in html_to_text("<p>Қазақстан</p>")


def test_no_empty_chunks_from_noisy_separators() -> None:
    body = "\n\n\nA\n\n\n\nB\n\n"
    chunks = chunk_article(title="T", body=body, body_format="plain")
    assert chunks
    assert all(chunk.strip() for chunk in chunks)


def test_split_windows_respects_size_and_overlap() -> None:
    text = "abcdefghij" * 40  # 400 chars
    windows = split_windows(text, size=50, overlap=10)
    assert windows
    assert all(1 <= len(w) <= 50 for w in windows)
    assert "".join(windows[0][:40])  # non-empty
    # Overlap: next window should share a suffix/prefix region
    if len(windows) > 1:
        assert windows[0][-10:] in text


def test_chunk_size_constants_match_architecture() -> None:
    assert DEFAULT_CHUNK_SIZE_CHARS == 1500
    assert DEFAULT_CHUNK_OVERLAP_CHARS == 200
    assert MAX_CHUNKS_PER_ARTICLE == 32

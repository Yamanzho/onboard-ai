"""Deterministic character chunking for knowledge article versions.

No LLM, no semantic splitter. Unicode-safe (RU / EN / KK) because slicing
operates on Python str (code points), not UTF-8 bytes.
"""

from __future__ import annotations

import re
from html import unescape

from app.core.ai_constants import (
    DEFAULT_CHUNK_OVERLAP_CHARS,
    DEFAULT_CHUNK_SIZE_CHARS,
    MAX_CHUNKS_PER_ARTICLE,
    SMALL_ARTICLE_CHARS,
)
from app.core.exceptions import ValidationError
from app.db.enums import KnowledgeBodyFormat

_BREAKS = ("\n## ", "\n# ", "\n\n", "\n", ". ", "? ", "! ", " ", "")
_TAG_RE = re.compile(r"<[^>]+>", re.DOTALL)
_SCRIPT_RE = re.compile(r"(?is)<script[^>]*>.*?</script>")
_STYLE_RE = re.compile(r"(?is)<style[^>]*>.*?</style>")


def html_to_text(html: str) -> str:
    """Best-effort HTML → text. Not a full browser, just indexable copy."""
    text = _SCRIPT_RE.sub(" ", html)
    text = _STYLE_RE.sub(" ", text)
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = re.sub(r"(?i)</p>", "\n\n", text)
    text = re.sub(r"(?i)</h[1-6]>", "\n", text)
    text = _TAG_RE.sub("", text)
    return unescape(text)


def _normalize(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n").strip()


def extract_index_text(*, title: str, body: str, body_format: str) -> tuple[str, str]:
    """Return normalized ``(title, body)`` ready for chunking."""
    title_n = _normalize(title)
    raw_body = body or ""
    if (body_format or "").lower() == KnowledgeBodyFormat.HTML.value:
        raw_body = html_to_text(raw_body)
    return title_n, _normalize(raw_body)


def _best_break(text: str, start: int, end: int) -> int:
    window = text[start:end]
    min_pos = max(len(window) // 2, 1)
    for sep in _BREAKS:
        if not sep:
            return end
        idx = window.rfind(sep)
        if idx >= min_pos:
            return start + idx + len(sep)
    return end


def split_windows(
    text: str,
    *,
    size: int = DEFAULT_CHUNK_SIZE_CHARS,
    overlap: int = DEFAULT_CHUNK_OVERLAP_CHARS,
) -> list[str]:
    """Split ``text`` into ordered windows. Empty input → empty list."""
    if isinstance(size, bool) or not isinstance(size, int) or size < 1:
        raise ValidationError("chunk size must be an integer >= 1")
    if isinstance(overlap, bool) or not isinstance(overlap, int):
        raise ValidationError("chunk overlap must be an integer")
    if overlap < 0 or overlap >= size:
        raise ValidationError("chunk overlap must be >= 0 and < chunk size")

    text = _normalize(text)
    if not text:
        return []
    if len(text) <= size:
        return [text]

    chunks: list[str] = []
    start = 0
    length = len(text)
    while start < length:
        end = min(start + size, length)
        if end < length:
            end = _best_break(text, start, end)
            if end <= start:
                end = min(start + size, length)
        piece = text[start:end].strip()
        if piece:
            chunks.append(piece)
        if end >= length:
            break
        next_start = end - overlap
        if next_start <= start:
            next_start = end
        start = next_start
    return chunks


def chunk_article(
    *,
    title: str,
    body: str,
    body_format: str = KnowledgeBodyFormat.MARKDOWN.value,
    chunk_size: int = DEFAULT_CHUNK_SIZE_CHARS,
    overlap: int = DEFAULT_CHUNK_OVERLAP_CHARS,
    max_chunks: int = MAX_CHUNKS_PER_ARTICLE,
) -> list[str]:
    """Deterministic chunks: same inputs always yield the same list.

    Each chunk is prefixed with the article title so retrieval can match
    policy names. Empty title+body returns an empty list (no blank chunks).
    """
    if max_chunks < 1:
        raise ValidationError("max_chunks must be >= 1")

    title_n, body_n = extract_index_text(title=title, body=body, body_format=body_format)
    if not title_n and not body_n:
        return []

    prefix = f"{title_n}\n\n" if title_n else ""
    if not body_n:
        return [title_n]

    combined_len = len(prefix) + len(body_n)
    if combined_len <= SMALL_ARTICLE_CHARS:
        content = f"{prefix}{body_n}" if prefix else body_n
        return [content] if content.strip() else []

    body_window = chunk_size - len(prefix)
    if body_window < 32:
        body_window = chunk_size

    pieces = split_windows(body_n, size=body_window, overlap=overlap)
    if len(pieces) > max_chunks:
        head = pieces[: max_chunks - 1]
        tail = "\n".join(pieces[max_chunks - 1 :])
        pieces = [*head, tail]

    chunks: list[str] = []
    for piece in pieces:
        content = f"{prefix}{piece}" if prefix else piece
        content = content.strip()
        if content:
            chunks.append(content)
    return chunks

"""Turn authorized RetrievalHit rows into LLM context and citations.

Does not query the database. Does not read chunk metadata for ACL.
Only hits already returned by KnowledgeRetriever may appear here.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from uuid import UUID

from app.core.ai_constants import (
    MAX_CONTEXT_CHARS_PER_DOC,
    MAX_CONTEXT_DOCUMENTS,
    MAX_CONTEXT_TOTAL_CHARS,
)
from app.core.exceptions import ValidationError
from app.services.ai.retriever import RetrievalHit


@dataclass(frozen=True, slots=True)
class Citation:
    """Grounding identity for a context document. Not an ACL grant."""

    source_id: str
    article_id: UUID
    version_id: UUID
    title: str
    chunk_index: int


@dataclass(frozen=True, slots=True)
class ContextDocument:
    source_id: str
    article_id: UUID
    version_id: UUID
    title: str
    chunk_index: int
    content: str

    def citation(self) -> Citation:
        return Citation(
            source_id=self.source_id,
            article_id=self.article_id,
            version_id=self.version_id,
            title=self.title,
            chunk_index=self.chunk_index,
        )


@dataclass(frozen=True, slots=True)
class ContextBundle:
    documents: tuple[ContextDocument, ...]

    @property
    def citations(self) -> tuple[Citation, ...]:
        return tuple(document.citation() for document in self.documents)

    def citations_for(self, source_ids: Sequence[str]) -> tuple[Citation, ...]:
        allowed = {document.source_id: document.citation() for document in self.documents}
        seen: list[Citation] = []
        used: set[str] = set()
        for source_id in source_ids:
            citation = allowed.get(source_id)
            if citation is None or source_id in used:
                continue
            used.add(source_id)
            seen.append(citation)
        return tuple(seen)


class KnowledgeContextBuilder:
    """Deterministic, size-limited context from retrieval hits only."""

    def __init__(
        self,
        *,
        max_documents: int = MAX_CONTEXT_DOCUMENTS,
        max_chars_per_doc: int = MAX_CONTEXT_CHARS_PER_DOC,
        max_total_chars: int = MAX_CONTEXT_TOTAL_CHARS,
    ) -> None:
        if max_documents < 1:
            raise ValidationError("max_documents must be at least 1")
        if max_chars_per_doc < 1:
            raise ValidationError("max_chars_per_doc must be at least 1")
        if max_total_chars < 1:
            raise ValidationError("max_total_chars must be at least 1")
        self._max_documents = max_documents
        self._max_chars_per_doc = max_chars_per_doc
        self._max_total_chars = max_total_chars

    def build(self, hits: Sequence[RetrievalHit]) -> ContextBundle:
        documents: list[ContextDocument] = []
        total = 0
        for index, hit in enumerate(hits):
            if len(documents) >= self._max_documents:
                break
            content = hit.content.strip()
            if not content:
                continue
            if len(content) > self._max_chars_per_doc:
                content = content[: self._max_chars_per_doc].rstrip()
            remaining = self._max_total_chars - total
            if remaining <= 0:
                break
            if len(content) > remaining:
                content = content[:remaining].rstrip()
            if not content:
                break
            source_id = f"S{index + 1}"
            documents.append(
                ContextDocument(
                    source_id=source_id,
                    article_id=hit.article_id,
                    version_id=hit.version_id,
                    title=hit.article_title.strip() or "Untitled",
                    chunk_index=hit.chunk_index,
                    content=content,
                )
            )
            total += len(content)
        return ContextBundle(documents=tuple(documents))

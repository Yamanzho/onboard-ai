"""KnowledgeContextBuilder: hits only, size limits, citation identities."""

from __future__ import annotations

from uuid import uuid4

import pytest

from app.core.exceptions import ValidationError
from app.services.ai.context import KnowledgeContextBuilder
from app.services.ai.retriever import RetrievalHit


def _hit(*, title: str = "T", content: str = "body", index: int = 0) -> RetrievalHit:
    return RetrievalHit(
        chunk_id=uuid4(),
        article_id=uuid4(),
        version_id=uuid4(),
        chunk_index=index,
        article_title=title,
        content=content,
        score=0.5,
    )


def test_builder_assigns_deterministic_source_ids_and_citations() -> None:
    first = _hit(title="Vacation", content="three days", index=0)
    second = _hit(title="VPN", content="WireGuard", index=1)
    bundle = KnowledgeContextBuilder().build([first, second])
    assert [doc.source_id for doc in bundle.documents] == ["S1", "S2"]
    citations = bundle.citations
    assert citations[0].article_id == first.article_id
    assert citations[0].version_id == first.version_id
    assert citations[0].title == "Vacation"
    assert citations[1].article_id == second.article_id


def test_builder_truncates_per_doc_and_total() -> None:
    hits = [
        _hit(content="A" * 80),
        _hit(content="B" * 80),
        _hit(content="C" * 80),
    ]
    bundle = KnowledgeContextBuilder(
        max_documents=2,
        max_chars_per_doc=10,
        max_total_chars=15,
    ).build(hits)
    assert len(bundle.documents) == 2
    assert bundle.documents[0].content == "A" * 10
    assert bundle.documents[1].content == "B" * 5
    assert sum(len(doc.content) for doc in bundle.documents) <= 15


def test_builder_skips_blank_and_ignores_unknown_cite_ids() -> None:
    kept = _hit(content="policy text")
    bundle = KnowledgeContextBuilder().build([_hit(content="  "), kept])
    assert len(bundle.documents) == 1
    assert bundle.documents[0].source_id == "S2"
    assert bundle.citations_for(["S99", "S2", "S2"]) == (bundle.citations[0],)


def test_builder_rejects_invalid_limits() -> None:
    with pytest.raises(ValidationError):
        KnowledgeContextBuilder(max_documents=0)

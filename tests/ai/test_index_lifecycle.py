"""AI-3: publish/edit/restore/archive keep the vector index as derived data."""

from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID

import pytest

from app.core.ai_constants import KB_CHUNK_VECTOR_DIMENSION
from app.core.exceptions import ValidationError
from app.db.enums import KnowledgeArticleStatus
from app.db.models.company import Company
from app.db.uow import UnitOfWork
from app.services.ai.indexer import INDEXING_RUNS_AFTER_KB_COMMIT, KnowledgeChunkIndexer
from app.services.knowledge.article_service import ArticleService
from tests.conftest import _uow_factory


@pytest.fixture
def indexer() -> KnowledgeChunkIndexer:
    return KnowledgeChunkIndexer(
        uow_factory=_uow_factory,
    )


class _BoomEmbeddings:
    dimension = KB_CHUNK_VECTOR_DIMENSION

    async def embed(self, text: str) -> list[float]:
        raise RuntimeError("embedding backend down")

    async def embed_batch(self, texts: Sequence[str]) -> list[list[float]]:
        raise RuntimeError("embedding backend down")


class _PartialBatchEmbeddings:
    """Returns fewer vectors than chunks so insert must not commit."""

    dimension = KB_CHUNK_VECTOR_DIMENSION

    async def embed(self, text: str) -> list[float]:
        return (await self.embed_batch((text,)))[0]

    async def embed_batch(self, texts: Sequence[str]) -> list[list[float]]:
        return []


async def _list_chunks(
    company_id: UUID,
    *,
    article_id: UUID | None = None,
    version_id: UUID | None = None,
):
    async with UnitOfWork() as uow:
        await uow.enter_tenant(company_id)
        if version_id is not None:
            return await uow.knowledge_article_chunks.list_by_version_id(version_id)
        assert article_id is not None
        return await uow.knowledge_article_chunks.list_by_article_id(article_id)


def test_indexing_is_explicitly_post_commit() -> None:
    assert INDEXING_RUNS_AFTER_KB_COMMIT is True


async def test_publish_creates_chunks_for_published_version(
    article_service: ArticleService,
    company_a: Company,
) -> None:
    draft = await article_service.create_article(
        company_id=company_a.id,
        actor_company_id=company_a.id,
        title="VPN",
        body="Use the company client.",
    )
    assert draft.current_version_id is not None
    assert await _list_chunks(company_a.id, article_id=draft.id) == []

    published = await article_service.publish_article(draft.id, company_id=company_a.id)
    chunks = await _list_chunks(company_a.id, version_id=published.current_version_id)
    assert chunks
    assert all(row.version_id == published.current_version_id for row in chunks)
    assert all(row.article_id == published.id for row in chunks)
    assert all(row.company_id == company_a.id for row in chunks)
    assert {row.chunk_index for row in chunks} == set(range(len(chunks)))
    assert "VPN" in chunks[0].content


async def test_draft_create_and_edit_do_not_create_chunks(
    article_service: ArticleService,
    company_a: Company,
) -> None:
    draft = await article_service.create_article(
        company_id=company_a.id,
        actor_company_id=company_a.id,
        title="Draft",
        body="not published yet",
    )
    edited = await article_service.update_article(
        draft.id,
        company_id=company_a.id,
        title="Draft v2",
        body="still a draft",
    )
    assert edited.status == KnowledgeArticleStatus.DRAFT.value
    assert await _list_chunks(company_a.id, article_id=edited.id) == []


async def test_draft_edit_after_publish_does_not_apply_this_product_has_no_shadow_draft(
    article_service: ArticleService,
    company_a: Company,
) -> None:
    """Existing ArticleService keeps status=published on content edit.

    There is no published-v1 + draft-v2 model. A content edit of a published
    article creates a new current version; that version is indexed. The previous
    version's chunks stay immutable.
    """
    published = await article_service.create_article(
        company_id=company_a.id,
        actor_company_id=company_a.id,
        title="Original",
        body="Body v1",
    )
    published = await article_service.publish_article(
        published.id,
        company_id=company_a.id,
    )
    v1 = published.current_version_id
    assert v1 is not None
    v1_chunks = await _list_chunks(company_a.id, version_id=v1)
    assert v1_chunks

    updated = await article_service.update_article(
        published.id,
        company_id=company_a.id,
        title="Updated",
        body="Body v2 which is still short",
    )
    v2 = updated.current_version_id
    assert v2 is not None and v2 != v1
    assert updated.status == KnowledgeArticleStatus.PUBLISHED.value

    still_v1 = await _list_chunks(company_a.id, version_id=v1)
    v2_chunks = await _list_chunks(company_a.id, version_id=v2)
    assert {row.id for row in still_v1} == {row.id for row in v1_chunks}
    assert still_v1[0].content == v1_chunks[0].content
    assert v2_chunks
    assert all(row.version_id == v2 for row in v2_chunks)
    assert "Updated" in v2_chunks[0].content


async def test_restore_published_indexes_new_version_and_keeps_old_chunks(
    article_service: ArticleService,
    company_a: Company,
) -> None:
    article = await article_service.create_article(
        company_id=company_a.id,
        actor_company_id=company_a.id,
        title="Original",
        body="Body v1",
    )
    article = await article_service.publish_article(article.id, company_id=company_a.id)
    v1 = article.current_version_id
    article = await article_service.update_article(
        article.id,
        company_id=company_a.id,
        title="Changed",
        body="Body v2",
    )
    v2 = article.current_version_id
    v1_chunks = await _list_chunks(company_a.id, version_id=v1)
    v2_chunks = await _list_chunks(company_a.id, version_id=v2)
    assert v1_chunks and v2_chunks

    restored = await article_service.restore_version(
        article.id,
        1,
        company_id=company_a.id,
        actor_role="hr",
    )
    v3 = restored.current_version_id
    assert v3 is not None and v3 not in {v1, v2}
    assert restored.status == KnowledgeArticleStatus.PUBLISHED.value
    assert restored.current_version is not None
    assert restored.current_version.body == "Body v1"

    still_v1 = await _list_chunks(company_a.id, version_id=v1)
    still_v2 = await _list_chunks(company_a.id, version_id=v2)
    v3_chunks = await _list_chunks(company_a.id, version_id=v3)
    assert {row.id for row in still_v1} == {row.id for row in v1_chunks}
    assert {row.id for row in still_v2} == {row.id for row in v2_chunks}
    assert v3_chunks
    assert all(row.version_id == v3 for row in v3_chunks)
    assert "Original" in v3_chunks[0].content


async def test_restore_draft_does_not_index(
    article_service: ArticleService,
    company_a: Company,
) -> None:
    article = await article_service.create_article(
        company_id=company_a.id,
        actor_company_id=company_a.id,
        title="Draft v1",
        body="first draft",
    )
    article = await article_service.update_article(
        article.id,
        company_id=company_a.id,
        title="Draft v2",
        body="second draft",
    )
    restored = await article_service.restore_version(
        article.id,
        1,
        company_id=company_a.id,
        actor_role="hr",
    )
    assert restored.status == KnowledgeArticleStatus.DRAFT.value
    assert await _list_chunks(company_a.id, article_id=restored.id) == []


async def test_archive_keeps_historical_chunks_and_rejects_reindex(
    article_service: ArticleService,
    company_a: Company,
    indexer: KnowledgeChunkIndexer,
) -> None:
    article = await article_service.create_article(
        company_id=company_a.id,
        actor_company_id=company_a.id,
        title="Soon archived",
        body="visible then gone",
    )
    article = await article_service.publish_article(article.id, company_id=company_a.id)
    version_id = article.current_version_id
    before = await _list_chunks(company_a.id, version_id=version_id)
    assert before

    archived = await article_service.archive_article(article.id, company_id=company_a.id)
    assert archived.status == KnowledgeArticleStatus.ARCHIVED.value
    after = await _list_chunks(company_a.id, version_id=version_id)
    assert {row.id for row in after} == {row.id for row in before}

    with pytest.raises(ValidationError, match="published"):
        await indexer.index_published_version(
            actor_company_id=company_a.id,
            article_id=article.id,
            version_id=version_id,  # type: ignore[arg-type]
        )


async def test_publish_twice_is_idempotent_chunk_set(
    article_service: ArticleService,
    company_a: Company,
    indexer: KnowledgeChunkIndexer,
) -> None:
    article = await article_service.create_article(
        company_id=company_a.id,
        actor_company_id=company_a.id,
        title="Stable",
        body="Same text",
    )
    article = await article_service.publish_article(article.id, company_id=company_a.id)
    assert article.current_version_id is not None
    first = await _list_chunks(company_a.id, version_id=article.current_version_id)
    second = await indexer.index_published_version(
        actor_company_id=company_a.id,
        article_id=article.id,
        version_id=article.current_version_id,
    )
    stored = await _list_chunks(company_a.id, version_id=article.current_version_id)
    assert len(first) == len(second) == len(stored)
    assert {row.chunk_index for row in stored} == {row.chunk_index for row in first}
    assert [(row.chunk_index, row.content) for row in stored] == [
        (row.chunk_index, row.content) for row in second
    ]
    # Unique (version_id, chunk_index) — no duplicates after a second index.
    indexes = [row.chunk_index for row in stored]
    assert indexes == list(range(len(stored)))


async def test_embedding_failure_on_publish_is_visible_and_leaves_article_published(
    company_a: Company,
) -> None:
    boom = KnowledgeChunkIndexer(
        uow_factory=_uow_factory,
        embedding_provider=_BoomEmbeddings(),  # type: ignore[arg-type]
    )
    service = ArticleService(uow_factory=_uow_factory, chunk_indexer=boom)
    draft = await service.create_article(
        company_id=company_a.id,
        actor_company_id=company_a.id,
        title="Will publish",
        body="KB stays readable if index fails",
    )
    with pytest.raises(RuntimeError, match="embedding backend down"):
        await service.publish_article(draft.id, company_id=company_a.id)

    loaded = await service.get_article(
        draft.id,
        company_id=company_a.id,
        actor_role="hr",
    )
    assert loaded.status == KnowledgeArticleStatus.PUBLISHED.value
    assert await _list_chunks(company_a.id, article_id=loaded.id) == []


async def test_embedding_failure_on_reindex_does_not_corrupt_existing_chunks(
    article_service: ArticleService,
    company_a: Company,
) -> None:
    article = await article_service.create_article(
        company_id=company_a.id,
        actor_company_id=company_a.id,
        title="Keep me",
        body="existing chunks must survive a failed reindex",
    )
    article = await article_service.publish_article(article.id, company_id=company_a.id)
    assert article.current_version_id is not None
    before = await _list_chunks(company_a.id, version_id=article.current_version_id)
    assert before

    boom = KnowledgeChunkIndexer(
        uow_factory=_uow_factory,
        embedding_provider=_BoomEmbeddings(),  # type: ignore[arg-type]
    )
    with pytest.raises(RuntimeError, match="embedding backend down"):
        await boom.index_published_version(
            actor_company_id=company_a.id,
            article_id=article.id,
            version_id=article.current_version_id,
        )
    after = await _list_chunks(company_a.id, version_id=article.current_version_id)
    assert {row.id for row in after} == {row.id for row in before}
    assert after[0].content == before[0].content


async def test_partial_embedding_batch_does_not_commit_chunks(
    company_a: Company,
) -> None:
    bad = KnowledgeChunkIndexer(
        uow_factory=_uow_factory,
        embedding_provider=_PartialBatchEmbeddings(),  # type: ignore[arg-type]
    )
    service = ArticleService(uow_factory=_uow_factory, chunk_indexer=bad)
    draft = await service.create_article(
        company_id=company_a.id,
        actor_company_id=company_a.id,
        title="Partial",
        body="must not leave a half-written index",
    )
    with pytest.raises(ValidationError, match="embedding batch size"):
        await service.publish_article(draft.id, company_id=company_a.id)
    loaded = await service.get_article(
        draft.id,
        company_id=company_a.id,
        actor_role="hr",
    )
    assert loaded.status == KnowledgeArticleStatus.PUBLISHED.value
    assert await _list_chunks(company_a.id, article_id=loaded.id) == []

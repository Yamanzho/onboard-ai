"""KnowledgeChunkIndexer: published current version only, tenant-bound."""

from __future__ import annotations

from uuid import uuid4

import pytest

from app.core.ai_constants import KB_CHUNK_VECTOR_DIMENSION
from app.core.exceptions import NotFoundError, ValidationError
from app.db.enums import KnowledgeArticleStatus
from app.db.models.company import Company
from app.db.uow import UnitOfWork
from app.services.ai.embeddings import FakeEmbeddingProvider
from app.services.ai.indexer import KnowledgeChunkIndexer
from app.services.knowledge.article_service import ArticleService
from tests.conftest import _uow_factory


@pytest.fixture
def indexer() -> KnowledgeChunkIndexer:
    return KnowledgeChunkIndexer(
        uow_factory=_uow_factory,
        embedding_provider=FakeEmbeddingProvider(),
    )


async def _publish(
    article_service: ArticleService,
    company: Company,
    *,
    title: str,
    body: str,
):
    article = await article_service.create_article(
        company_id=company.id,
        actor_company_id=company.id,
        title=title,
        body=body,
    )
    return await article_service.publish_article(article.id, company_id=company.id)


async def test_indexes_published_current_version(
    article_service: ArticleService,
    company_a: Company,
    indexer: KnowledgeChunkIndexer,
) -> None:
    article = await _publish(
        article_service,
        company_a,
        title="Vacation",
        body="Submit the form three days in advance.",
    )
    assert article.current_version_id is not None
    chunks = await indexer.index_published_version(
        actor_company_id=company_a.id,
        article_id=article.id,
        version_id=article.current_version_id,
    )
    assert chunks
    assert chunks[0].company_id == company_a.id
    assert chunks[0].article_id == article.id
    assert chunks[0].version_id == article.current_version_id
    assert chunks[0].chunk_index == 0
    assert "Vacation" in chunks[0].content
    assert len(chunks[0].embedding) == KB_CHUNK_VECTOR_DIMENSION
    assert chunks[0].extra["status"] == KnowledgeArticleStatus.PUBLISHED.value
    assert chunks[0].extra["visibility"] == article.visibility
    assert chunks[0].extra["embedding_model"] == "fake"
    assert "program_ids" in chunks[0].extra


async def test_repeated_indexing_replaces_same_version_only(
    article_service: ArticleService,
    company_a: Company,
    indexer: KnowledgeChunkIndexer,
) -> None:
    article = await _publish(
        article_service,
        company_a,
        title="VPN",
        body="Use the company client.",
    )
    assert article.current_version_id is not None
    first = await indexer.index_published_version(
        actor_company_id=company_a.id,
        article_id=article.id,
        version_id=article.current_version_id,
    )
    second = await indexer.index_published_version(
        actor_company_id=company_a.id,
        article_id=article.id,
        version_id=article.current_version_id,
    )
    assert len(first) == len(second)
    first_ids = {row.id for row in first}
    second_ids = {row.id for row in second}
    assert first_ids.isdisjoint(second_ids)

    async with UnitOfWork() as uow:
        await uow.enter_tenant(company_a.id)
        stored = await uow.knowledge_article_chunks.list_by_version_id(
            article.current_version_id
        )
    assert {row.id for row in stored} == second_ids


async def test_new_version_does_not_mutate_old_chunks(
    article_service: ArticleService,
    company_a: Company,
    indexer: KnowledgeChunkIndexer,
) -> None:
    article = await _publish(
        article_service,
        company_a,
        title="Original",
        body="Body v1",
    )
    v1 = article.current_version_id
    assert v1 is not None
    old_chunks = await indexer.index_published_version(
        actor_company_id=company_a.id,
        article_id=article.id,
        version_id=v1,
    )

    updated = await article_service.update_article(
        article.id,
        company_id=company_a.id,
        title="Updated",
        body="Body v2 which is still short",
    )
    v2 = updated.current_version_id
    assert v2 is not None and v2 != v1
    new_chunks = await indexer.index_published_version(
        actor_company_id=company_a.id,
        article_id=article.id,
        version_id=v2,
    )

    async with UnitOfWork() as uow:
        await uow.enter_tenant(company_a.id)
        v1_rows = await uow.knowledge_article_chunks.list_by_version_id(v1)
        v2_rows = await uow.knowledge_article_chunks.list_by_version_id(v2)
        all_rows = await uow.knowledge_article_chunks.list_by_article_id(article.id)
    assert {row.id for row in v1_rows} == {row.id for row in old_chunks}
    assert v1_rows[0].content == old_chunks[0].content
    assert {row.id for row in v2_rows} == {row.id for row in new_chunks}
    assert len(all_rows) == len(old_chunks) + len(new_chunks)


async def test_wrong_company_cannot_index_foreign_article(
    article_service: ArticleService,
    company_a: Company,
    company_b: Company,
    indexer: KnowledgeChunkIndexer,
) -> None:
    article_b = await _publish(
        article_service,
        company_b,
        title="Secret B",
        body="Tenant B only",
    )
    assert article_b.current_version_id is not None
    with pytest.raises(NotFoundError, match="not found"):
        await indexer.index_published_version(
            actor_company_id=company_a.id,
            article_id=article_b.id,
            version_id=article_b.current_version_id,
        )


async def test_unpublished_version_is_rejected(
    article_service: ArticleService,
    company_a: Company,
    indexer: KnowledgeChunkIndexer,
) -> None:
    draft = await article_service.create_article(
        company_id=company_a.id,
        actor_company_id=company_a.id,
        title="Draft",
        body="not published",
    )
    assert draft.current_version_id is not None
    with pytest.raises(ValidationError, match="published"):
        await indexer.index_published_version(
            actor_company_id=company_a.id,
            article_id=draft.id,
            version_id=draft.current_version_id,
        )


async def test_archived_article_is_rejected(
    article_service: ArticleService,
    company_a: Company,
    indexer: KnowledgeChunkIndexer,
) -> None:
    article = await _publish(
        article_service,
        company_a,
        title="Soon archived",
        body="visible then gone",
    )
    await article_service.archive_article(article.id, company_id=company_a.id)
    assert article.current_version_id is not None
    with pytest.raises(ValidationError, match="published"):
        await indexer.index_published_version(
            actor_company_id=company_a.id,
            article_id=article.id,
            version_id=article.current_version_id,
        )


async def test_wrong_version_id_is_rejected(
    article_service: ArticleService,
    company_a: Company,
    indexer: KnowledgeChunkIndexer,
) -> None:
    article = await _publish(
        article_service,
        company_a,
        title="V1",
        body="first",
    )
    v1 = article.current_version_id
    updated = await article_service.update_article(
        article.id,
        company_id=company_a.id,
        title="V2",
        body="second",
    )
    v2 = updated.current_version_id
    assert v1 is not None and v2 is not None and v1 != v2
    with pytest.raises(ValidationError, match="current published version"):
        await indexer.index_published_version(
            actor_company_id=company_a.id,
            article_id=article.id,
            version_id=v1,
        )


async def test_unknown_article_id_is_not_found(
    company_a: Company,
    indexer: KnowledgeChunkIndexer,
) -> None:
    with pytest.raises(NotFoundError, match="not found"):
        await indexer.index_published_version(
            actor_company_id=company_a.id,
            article_id=uuid4(),
            version_id=uuid4(),
        )


async def test_dimension_mismatch_is_rejected(
    article_service: ArticleService,
    company_a: Company,
) -> None:
    article = await _publish(
        article_service,
        company_a,
        title="Dim",
        body="check",
    )
    bad = KnowledgeChunkIndexer(
        uow_factory=_uow_factory,
        embedding_provider=FakeEmbeddingProvider(dimension=4),
    )
    with pytest.raises(ValidationError, match="embedding dimension mismatch"):
        await bad.index_published_version(
            actor_company_id=company_a.id,
            article_id=article.id,
            version_id=article.current_version_id,  # type: ignore[arg-type]
        )


async def test_fake_embeddings_are_deterministic_across_reindex(
    article_service: ArticleService,
    company_a: Company,
    indexer: KnowledgeChunkIndexer,
) -> None:
    article = await _publish(
        article_service,
        company_a,
        title="Stable",
        body="Same text",
    )
    assert article.current_version_id is not None
    first = await indexer.index_published_version(
        actor_company_id=company_a.id,
        article_id=article.id,
        version_id=article.current_version_id,
    )
    second = await indexer.index_published_version(
        actor_company_id=company_a.id,
        article_id=article.id,
        version_id=article.current_version_id,
    )
    assert first[0].embedding == second[0].embedding
    assert first[0].content == second[0].content

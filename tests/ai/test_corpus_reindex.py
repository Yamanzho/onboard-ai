"""AI-6 tenant corpus reindex: published current versions only, JWT tenant."""

from __future__ import annotations

from collections.abc import Sequence
from uuid import uuid4

import pytest

from app.core.exceptions import ForbiddenError, NotFoundError
from app.db.enums import EmployeeRole, KnowledgeArticleStatus, PlatformRole
from app.db.models.company import Company
from app.db.models.employee import Employee
from app.db.uow import UnitOfWork
from app.services.ai.embeddings import FakeEmbeddingProvider
from app.services.ai.indexer import KnowledgeChunkIndexer
from app.services.knowledge.article_service import ArticleService
from tests.conftest import _uow_factory, auth_header


class _SelectiveFailureEmbeddings:
    dimension = 1536
    model = "fake"
    provider_name = "fake"

    def __init__(self) -> None:
        self._delegate = FakeEmbeddingProvider()

    async def embed(self, text: str) -> list[float]:
        return (await self.embed_batch((text,)))[0]

    async def embed_batch(self, texts: Sequence[str]) -> list[list[float]]:
        if any("FAIL_CORPUS" in text for text in texts):
            raise RuntimeError("provider unavailable")
        return await self._delegate.embed_batch(texts)


@pytest.fixture
def indexer() -> KnowledgeChunkIndexer:
    return KnowledgeChunkIndexer(
        uow_factory=_uow_factory,
        embedding_provider=FakeEmbeddingProvider(),
    )


async def _publish(article_service: ArticleService, company: Company, *, title: str, body: str):
    article = await article_service.create_article(
        company_id=company.id,
        actor_company_id=company.id,
        title=title,
        body=body,
    )
    return await article_service.publish_article(article.id, company_id=company.id)


async def test_corpus_reindex_covers_published_not_drafts(
    article_service: ArticleService,
    indexer: KnowledgeChunkIndexer,
    company_a: Company,
    hr_a: Employee,
) -> None:
    first = await _publish(article_service, company_a, title="One", body="first body")
    second = await _publish(article_service, company_a, title="Two", body="second body")
    draft = await article_service.create_article(
        company_id=company_a.id,
        actor_company_id=company_a.id,
        title="Draft",
        body="not indexed",
    )
    async with UnitOfWork() as uow:
        await uow.enter_tenant(company_a.id)
        await uow.knowledge_article_chunks.delete_by_version_id(first.current_version_id)
        await uow.knowledge_article_chunks.delete_by_version_id(second.current_version_id)
        await uow.commit()

    result = await indexer.reindex_published_corpus(
        actor_company_id=company_a.id,
        actor_employee_id=hr_a.id,
        actor_role=EmployeeRole.HR.value,
    )
    assert result.indexed_articles == 2
    assert result.indexed_chunks >= 2
    async with UnitOfWork() as uow:
        await uow.enter_tenant(company_a.id)
        assert await uow.knowledge_article_chunks.list_by_article_id(first.id)
        assert await uow.knowledge_article_chunks.list_by_article_id(second.id)
        assert await uow.knowledge_article_chunks.list_by_article_id(draft.id) == []
    assert draft.status == KnowledgeArticleStatus.DRAFT.value


async def test_corpus_reindex_rejects_employee_and_super_admin(
    indexer: KnowledgeChunkIndexer,
    company_a: Company,
    employee_a: Employee,
) -> None:
    with pytest.raises(ForbiddenError, match="HR or Admin"):
        await indexer.reindex_published_corpus(
            actor_company_id=company_a.id,
            actor_employee_id=employee_a.id,
            actor_role=EmployeeRole.EMPLOYEE.value,
        )
    with pytest.raises(ForbiddenError, match="impersonation"):
        await indexer.reindex_published_corpus(
            actor_company_id=company_a.id,
            actor_employee_id=uuid4(),
            actor_role=PlatformRole.SUPER_ADMIN.value,
        )


async def test_company_a_cannot_corpus_reindex_company_b(
    article_service: ArticleService,
    indexer: KnowledgeChunkIndexer,
    company_a: Company,
    company_b: Company,
    hr_a: Employee,
) -> None:
    article_b = await _publish(article_service, company_b, title="B", body="secret B")
    assert article_b.current_version_id is not None
    async with UnitOfWork() as uow:
        await uow.enter_tenant(company_b.id)
        before = await uow.knowledge_article_chunks.list_by_version_id(article_b.current_version_id)
    assert before

    with pytest.raises(NotFoundError):
        await indexer.reindex_published_corpus(
            actor_company_id=company_a.id,
            actor_employee_id=hr_a.id,
            actor_role=EmployeeRole.HR.value,
            claimed_company_id=company_b.id,
        )

    result = await indexer.reindex_published_corpus(
        actor_company_id=company_a.id,
        actor_employee_id=hr_a.id,
        actor_role=EmployeeRole.HR.value,
    )
    assert result.indexed_articles == 0
    async with UnitOfWork() as uow:
        await uow.enter_tenant(company_b.id)
        after = await uow.knowledge_article_chunks.list_by_version_id(article_b.current_version_id)
    assert {row.id for row in after} == {row.id for row in before}


async def test_corpus_reindex_reports_partial_failure_and_continues(
    article_service: ArticleService,
    company_a: Company,
    hr_a: Employee,
) -> None:
    good = await _publish(article_service, company_a, title="Good", body="GOOD_CORPUS")
    failed = await _publish(
        article_service,
        company_a,
        title="Bad",
        body="FAIL_CORPUS",
    )
    indexer = KnowledgeChunkIndexer(
        uow_factory=_uow_factory,
        embedding_provider=_SelectiveFailureEmbeddings(),  # type: ignore[arg-type]
    )
    result = await indexer.reindex_published_corpus(
        actor_company_id=company_a.id,
        actor_employee_id=hr_a.id,
        actor_role=EmployeeRole.HR.value,
    )
    assert result.attempted_articles == 2
    assert result.succeeded_articles == 1
    assert result.failed_articles == 1
    assert result.complete is False
    assert {item.article_id for item in result.items} == {good.id, failed.id}
    failed_item = next(item for item in result.items if item.article_id == failed.id)
    assert failed_item.status == "failed"
    assert failed_item.failure_category == "internal"

    loaded = await article_service.get_article(
        failed.id,
        company_id=company_a.id,
        actor_role=EmployeeRole.HR.value,
    )
    assert loaded.current_version is not None
    assert loaded.current_version.index_status == "indexed"
    assert loaded.current_version.index_stale is True


async def test_http_corpus_reindex_hr_admin_employee(
    api_client,
    article_service: ArticleService,
    company_a: Company,
    company_b: Company,
    hr_a: Employee,
    admin_a: Employee,
    employee_a: Employee,
) -> None:
    await _publish(article_service, company_a, title="A pub", body="corpus")
    employee = await api_client.post(
        "/api/v1/knowledge/articles/reindex-published",
        headers=auth_header(employee_a),
    )
    assert employee.status_code == 403

    hr = await api_client.post(
        "/api/v1/knowledge/articles/reindex-published",
        headers=auth_header(hr_a),
    )
    assert hr.status_code == 200, hr.text
    body = hr.json()
    assert body["indexed_articles"] >= 1
    assert body["indexed_chunks"] >= 1
    assert body["attempted_articles"] == body["succeeded_articles"]
    assert body["failed_articles"] == 0
    assert body["complete"] is True
    assert all(item["status"] == "indexed" for item in body["items"])

    admin = await api_client.post(
        "/api/v1/knowledge/articles/reindex-published",
        headers=auth_header(admin_a),
        params={"company_id": str(company_a.id)},
    )
    assert admin.status_code == 200, admin.text

    spoof = await api_client.post(
        "/api/v1/knowledge/articles/reindex-published",
        headers=auth_header(hr_a),
        params={"company_id": str(company_b.id)},
    )
    assert spoof.status_code == 404

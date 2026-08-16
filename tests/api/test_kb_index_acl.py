"""Tenant isolation for automatic KB indexing. Never trust caller company_id."""

from __future__ import annotations

from uuid import UUID

import pytest

from app.core.exceptions import NotFoundError
from app.db.models.company import Company
from app.db.models.employee import Employee
from app.db.uow import UnitOfWork
from app.services.ai.indexer import KnowledgeChunkIndexer
from app.services.knowledge.article_service import ArticleService
from tests.conftest import _uow_factory, auth_header


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


async def _publish(article_service: ArticleService, company: Company, *, title: str, body: str):
    article = await article_service.create_article(
        company_id=company.id,
        actor_company_id=company.id,
        title=title,
        body=body,
    )
    return await article_service.publish_article(article.id, company_id=company.id)


@pytest.fixture
def indexer() -> KnowledgeChunkIndexer:
    return KnowledgeChunkIndexer(uow_factory=_uow_factory)


async def test_authenticated_a_cannot_index_b_with_spoofed_company_ids(
    api_client,
    hr_a: Employee,
    article_service: ArticleService,
    company_b: Company,
    indexer: KnowledgeChunkIndexer,
) -> None:
    """Company A authenticates, then calls indexing with B's identifiers.

    Expected: rejected. ``company_id`` from the caller is not RLS authority.
    """
    article_b = await _publish(
        article_service,
        company_b,
        title="Secret B",
        body="Tenant B handbook",
    )
    assert article_b.current_version_id is not None
    before = await _list_chunks(company_b.id, version_id=article_b.current_version_id)
    assert before

    # JWT tenant is A (hr_a.company_id). Payload claims B.
    with pytest.raises(NotFoundError, match="not found"):
        await indexer.index_published_version(
            actor_company_id=hr_a.company_id,
            company_id=company_b.id,
            article_id=article_b.id,
            version_id=article_b.current_version_id,
        )

    response = await api_client.post(
        f"/api/v1/knowledge/articles/{article_b.id}/reindex",
        headers=auth_header(hr_a),
        params={
            "company_id": str(company_b.id),
            "version_id": str(article_b.current_version_id),
        },
    )
    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()

    after = await _list_chunks(company_b.id, version_id=article_b.current_version_id)
    assert {row.id for row in after} == {row.id for row in before}
    assert after[0].content == before[0].content


async def test_company_a_cannot_index_company_b_article(
    article_service: ArticleService,
    company_a: Company,
    company_b: Company,
    indexer: KnowledgeChunkIndexer,
) -> None:
    article_b = await _publish(
        article_service,
        company_b,
        title="B only",
        body="not for A",
    )
    with pytest.raises(NotFoundError, match="not found"):
        await indexer.index_published_version(
            actor_company_id=company_a.id,
            article_id=article_b.id,
            version_id=article_b.current_version_id,  # type: ignore[arg-type]
        )
    # UUID probing: missing and foreign look the same.
    with pytest.raises(NotFoundError, match="not found"):
        await indexer.index_published_version(
            actor_company_id=company_a.id,
            article_id=article_b.id,
            version_id=article_b.current_version_id,  # type: ignore[arg-type]
            company_id=company_a.id,
        )


async def test_company_a_cannot_replace_or_delete_company_b_chunks(
    article_service: ArticleService,
    company_a: Company,
    company_b: Company,
    indexer: KnowledgeChunkIndexer,
) -> None:
    article_a = await _publish(
        article_service,
        company_a,
        title="A handbook",
        body="A body",
    )
    article_b = await _publish(
        article_service,
        company_b,
        title="B handbook",
        body="B body must stay",
    )
    assert article_b.current_version_id is not None
    b_before = await _list_chunks(company_b.id, version_id=article_b.current_version_id)
    assert b_before

    with pytest.raises(NotFoundError, match="not found"):
        await indexer.index_published_version(
            actor_company_id=company_a.id,
            company_id=company_b.id,
            article_id=article_b.id,
            version_id=article_b.current_version_id,
        )

    b_after = await _list_chunks(company_b.id, version_id=article_b.current_version_id)
    assert {row.id for row in b_after} == {row.id for row in b_before}
    assert b_after[0].content == b_before[0].content

    a_chunks = await _list_chunks(company_a.id, article_id=article_a.id)
    assert a_chunks
    assert all(row.company_id == company_a.id for row in a_chunks)


async def test_hr_a_cannot_reindex_b_via_http(
    api_client,
    hr_a: Employee,
    article_service: ArticleService,
    company_b: Company,
) -> None:
    article_b = await _publish(
        article_service,
        company_b,
        title="B http",
        body="B http body",
    )
    response = await api_client.post(
        f"/api/v1/knowledge/articles/{article_b.id}/reindex",
        headers=auth_header(hr_a),
    )
    assert response.status_code == 404


async def test_hr_a_reindex_own_published_article_is_idempotent(
    api_client,
    hr_a: Employee,
    article_service: ArticleService,
    company_a: Company,
) -> None:
    article = await _publish(
        article_service,
        company_a,
        title="Own",
        body="reindex me",
    )
    assert article.current_version_id is not None
    first = await _list_chunks(company_a.id, version_id=article.current_version_id)
    response = await api_client.post(
        f"/api/v1/knowledge/articles/{article.id}/reindex",
        headers=auth_header(hr_a),
        params={"company_id": str(company_a.id)},
    )
    assert response.status_code == 200, response.text
    second = await _list_chunks(company_a.id, version_id=article.current_version_id)
    assert len(first) == len(second)
    assert {row.chunk_index for row in second} == {row.chunk_index for row in first}


async def test_employee_cannot_reindex(
    api_client,
    employee_a: Employee,
    article_service: ArticleService,
    company_a: Company,
) -> None:
    article = await _publish(
        article_service,
        company_a,
        title="Emp",
        body="no reindex for employees",
    )
    response = await api_client.post(
        f"/api/v1/knowledge/articles/{article.id}/reindex",
        headers=auth_header(employee_a),
    )
    assert response.status_code == 403


async def test_publish_http_indexes_only_caller_tenant(
    api_client,
    hr_a: Employee,
    hr_b: Employee,
    company_a: Company,
    company_b: Company,
) -> None:
    created = await api_client.post(
        "/api/v1/knowledge/articles",
        headers=auth_header(hr_a),
        json={
            "company_id": str(company_a.id),
            "title": "A published",
            "body": "A only",
            "visibility": "company",
        },
    )
    assert created.status_code == 201, created.text
    article_id = created.json()["id"]
    published = await api_client.post(
        f"/api/v1/knowledge/articles/{article_id}/publish",
        headers=auth_header(hr_a),
    )
    assert published.status_code == 200, published.text
    version_id = UUID(published.json()["current_version"]["id"])
    chunks = await _list_chunks(company_a.id, version_id=version_id)
    assert chunks
    assert all(row.company_id == company_a.id for row in chunks)

    # B cannot publish A's draft (already published) or probe the id.
    foreign = await api_client.post(
        f"/api/v1/knowledge/articles/{article_id}/publish",
        headers=auth_header(hr_b),
    )
    assert foreign.status_code == 404
    b_view = await _list_chunks(company_b.id, article_id=UUID(article_id))
    assert b_view == []

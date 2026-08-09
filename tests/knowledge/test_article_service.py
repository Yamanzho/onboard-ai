"""ArticleService lifecycle, versioning, tenancy, and SQLAlchemy safety."""

from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy import event

import app.db.session as db_session
from app.core.exceptions import NotFoundError, ValidationError
from app.db.enums import KnowledgeArticleStatus
from app.db.models.company import Company
from app.db.models.employee import Employee
from app.db.models.knowledge_article_version import KnowledgeArticleVersion
from app.db.uow import UnitOfWork
from app.services.knowledge.article_service import ArticleService
from app.services.knowledge.category_service import CategoryService
from app.services.knowledge.tag_service import TagService
from tests.conftest import auth_header


@pytest.mark.asyncio
async def test_create_article_creates_article_and_version_1(
    article_service: ArticleService,
    company_a: Company,
    hr_a: Employee,
) -> None:
    article = await article_service.create_article(
        company_id=company_a.id,
        actor_company_id=company_a.id,
        title="VPN setup",
        body="Step one",
        created_by_id=hr_a.id,
    )

    assert article.status == KnowledgeArticleStatus.DRAFT.value
    assert article.current_version_id is not None
    assert article.current_version is not None
    assert article.current_version.version == 1
    assert article.current_version.title == "VPN setup"
    assert article.current_version.body == "Step one"
    # Eager-loaded relations remain readable after UoW session close.
    assert article.tags == []


@pytest.mark.asyncio
async def test_update_article_creates_new_version_and_keeps_old(
    article_service: ArticleService,
    company_a: Company,
) -> None:
    article = await article_service.create_article(
        company_id=company_a.id,
        actor_company_id=company_a.id,
        title="Original",
        body="Body v1",
    )
    v1_id = article.current_version_id
    assert v1_id is not None

    updated = await article_service.update_article(
        article.id,
        company_id=company_a.id,
        title="Updated",
        body="Body v2",
        change_summary="revise",
    )

    assert updated.current_version is not None
    assert updated.current_version.version == 2
    assert updated.current_version.title == "Updated"
    assert updated.current_version.body == "Body v2"
    assert updated.current_version_id != v1_id

    async with UnitOfWork() as uow:
        await uow.enter_platform()
        old = await uow.session.get(KnowledgeArticleVersion, v1_id)
        assert old is not None
        assert old.version == 1
        assert old.title == "Original"
        assert old.body == "Body v1"


@pytest.mark.asyncio
async def test_publish_draft_article(
    article_service: ArticleService,
    company_a: Company,
) -> None:
    article = await article_service.create_article(
        company_id=company_a.id,
        actor_company_id=company_a.id,
        title="Publish me",
        body="Ready",
    )
    published = await article_service.publish_article(
        article.id,
        company_id=company_a.id,
    )
    assert published.status == KnowledgeArticleStatus.PUBLISHED.value
    assert published.current_version is not None
    assert published.current_version.published_at is not None


@pytest.mark.asyncio
async def test_cannot_publish_archived_article(
    article_service: ArticleService,
    company_a: Company,
) -> None:
    article = await article_service.create_article(
        company_id=company_a.id,
        actor_company_id=company_a.id,
        title="Archive then publish",
        body="x",
    )
    await article_service.archive_article(article.id, company_id=company_a.id)

    with pytest.raises(ValidationError, match="Invalid status transition"):
        await article_service.publish_article(article.id, company_id=company_a.id)


@pytest.mark.asyncio
async def test_archive_article(
    article_service: ArticleService,
    company_a: Company,
) -> None:
    article = await article_service.create_article(
        company_id=company_a.id,
        actor_company_id=company_a.id,
        title="To archive",
        body="x",
    )
    archived = await article_service.archive_article(
        article.id,
        company_id=company_a.id,
    )
    assert archived.status == KnowledgeArticleStatus.ARCHIVED.value


@pytest.mark.asyncio
async def test_get_article_not_found(article_service: ArticleService, company_a: Company) -> None:
    with pytest.raises(NotFoundError, match="not found"):
        await article_service.get_article(
            uuid4(),
            company_id=company_a.id,
            actor_role="hr",
        )


@pytest.mark.asyncio
async def test_cannot_get_article_from_other_company(
    article_service: ArticleService,
    company_a: Company,
    company_b: Company,
) -> None:
    article = await article_service.create_article(
        company_id=company_a.id,
        actor_company_id=company_a.id,
        title="Tenant A only",
        body="secret",
    )
    with pytest.raises(NotFoundError, match="not found"):
        await article_service.get_article(
            article.id,
            company_id=company_b.id,
            actor_role="hr",
        )


@pytest.mark.asyncio
async def test_cannot_assign_category_from_other_company(
    article_service: ArticleService,
    category_service: CategoryService,
    company_a: Company,
    company_b: Company,
) -> None:
    foreign_category = await category_service.create_category(
        company_id=company_b.id,
        actor_company_id=company_b.id,
        name="Foreign",
        slug="foreign-cat",
    )
    with pytest.raises(NotFoundError, match="category"):
        await article_service.create_article(
            company_id=company_a.id,
            actor_company_id=company_a.id,
            title="Bad category",
            body="x",
            category_id=foreign_category.id,
        )


@pytest.mark.asyncio
async def test_returned_article_has_no_lazy_loads_after_session_close(
    article_service: ArticleService,
    category_service: CategoryService,
    tag_service: TagService,
    company_a: Company,
) -> None:
    category = await category_service.create_category(
        company_id=company_a.id,
        actor_company_id=company_a.id,
        name="Policies",
        slug="policies",
    )
    tag = await tag_service.create_tag(
        company_id=company_a.id,
        actor_company_id=company_a.id,
        name="Security",
        slug="security",
    )
    article = await article_service.create_article(
        company_id=company_a.id,
        actor_company_id=company_a.id,
        title="Eager load check",
        body="body",
        category_id=category.id,
        tag_ids=[tag.id],
    )

    # Outside any UnitOfWork — must not trigger IO or DetachedInstanceError.
    assert article.current_version is not None
    assert article.current_version.title == "Eager load check"
    assert len(article.tags) == 1
    assert article.tags[0].slug == "security"
    assert article.category is not None
    assert article.category.slug == "policies"


@pytest.mark.asyncio
async def test_list_articles_eager_loads_relations_without_n_plus_one(
    article_service: ArticleService,
    company_a: Company,
) -> None:
    await article_service.create_article(
        company_id=company_a.id,
        actor_company_id=company_a.id,
        title="One",
        body="a",
    )
    await article_service.create_article(
        company_id=company_a.id,
        actor_company_id=company_a.id,
        title="Two",
        body="b",
    )

    statements: list[str] = []

    def _before_cursor_execute(
        _conn,
        _cursor,
        statement: str,
        _parameters,
        _context,
        _executemany,
    ) -> None:
        statements.append(statement)

    bind = db_session.engine.sync_engine
    event.listen(bind, "before_cursor_execute", _before_cursor_execute)
    try:
        articles = await article_service.list_articles(
            company_a.id,
            actor_company_id=company_a.id,
        )
        titles = [a.current_version.title for a in articles if a.current_version]
        assert set(titles) == {"One", "Two"}
        # Detached access after UoW close must not raise.
        assert all(a.tags is not None for a in articles)
    finally:
        event.remove(bind, "before_cursor_execute", _before_cursor_execute)

    select_count = sum(
        1
        for s in statements
        if s.lstrip().upper().startswith("SELECT")
        and "set_config(" not in s.lower()
    )
    # company lookup + list + selectinload batches (version/tags/links/category).
    # SEC-R3 set_config GUC helpers are excluded (security plumbing, not N+1).
    assert select_count <= 8


@pytest.mark.asyncio
async def test_api_article_not_found_returns_404(
    api_client,
    hr_a: Employee,
) -> None:
    missing_id = uuid4()
    response = await api_client.get(
        f"/api/v1/knowledge/articles/{missing_id}",
        headers=auth_header(hr_a),
    )
    assert response.status_code == 404
    assert "not found" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_api_invalid_status_transition_returns_400(
    api_client,
    article_service: ArticleService,
    company_a: Company,
    hr_a: Employee,
) -> None:
    """Business ValidationError maps to HTTP 400 (not 422) in this codebase."""
    article = await article_service.create_article(
        company_id=company_a.id,
        actor_company_id=company_a.id,
        title="Archived",
        body="x",
    )
    await article_service.archive_article(article.id, company_id=company_a.id)

    response = await api_client.post(
        f"/api/v1/knowledge/articles/{article.id}/publish",
        headers=auth_header(hr_a),
    )
    assert response.status_code == 400
    assert "Invalid status transition" in response.json()["detail"]


@pytest.mark.asyncio
async def test_api_cross_tenant_get_returns_404(
    api_client,
    article_service: ArticleService,
    company_a: Company,
    hr_b: Employee,
) -> None:
    article = await article_service.create_article(
        company_id=company_a.id,
        actor_company_id=company_a.id,
        title="Private",
        body="x",
    )
    response = await api_client.get(
        f"/api/v1/knowledge/articles/{article.id}",
        headers=auth_header(hr_b),
    )
    assert response.status_code == 404

"""P1-KB-ACL: employees must not read draft/archived or unauthorized program articles."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from httpx import AsyncClient

from app.core.exceptions import NotFoundError
from app.db.enums import (
    AssignmentStatus,
    EmployeeRole,
    KnowledgeArticleStatus,
    KnowledgeLinkTargetType,
    KnowledgeVisibility,
)
from app.db.models.assignment import Assignment
from app.db.models.company import Company
from app.db.models.employee import Employee
from app.db.models.knowledge_article_link import KnowledgeArticleLink
from app.db.models.onboarding_program import OnboardingProgram
from app.db.uow import UnitOfWork
from app.services.knowledge.article_service import ArticleService
from tests.conftest import _uow_factory, auth_header


async def _create_program(company_id) -> OnboardingProgram:
    async with _uow_factory() as uow:
        await uow.enter_platform()
        program = await uow.onboarding_programs.create(
            OnboardingProgram(
                company_id=company_id,
                title=f"Program {uuid4().hex[:8]}",
                is_active=True,
            ),
        )
        await uow.commit()
        return program


async def _assign_employee(
    *,
    company_id,
    employee_id,
    program_id,
    status: str = AssignmentStatus.IN_PROGRESS.value,
) -> Assignment:
    async with _uow_factory() as uow:
        await uow.enter_platform()
        assignment = await uow.assignments.create(
            Assignment(
                company_id=company_id,
                employee_id=employee_id,
                program_id=program_id,
                status=status,
                assigned_at=datetime.now(UTC),
            ),
        )
        await uow.commit()
        return assignment


async def _link_article_to_program(
    *,
    company_id,
    article_id,
    program_id,
) -> None:
    async with _uow_factory() as uow:
        await uow.enter_platform()
        await uow.knowledge_article_links.create(
            KnowledgeArticleLink(
                company_id=company_id,
                article_id=article_id,
                target_type=KnowledgeLinkTargetType.PROGRAM.value,
                target_id=program_id,
            ),
        )
        await uow.commit()


@pytest.mark.asyncio
async def test_employee_can_read_published_company_visibility_article(
    api_client: AsyncClient,
    article_service: ArticleService,
    company_a: Company,
    employee_a: Employee,
) -> None:
    article = await article_service.create_article(
        company_id=company_a.id,
        actor_company_id=company_a.id,
        title="Company handbook",
        body="Welcome published body",
        visibility=KnowledgeVisibility.COMPANY.value,
    )
    published = await article_service.publish_article(
        article.id,
        company_id=company_a.id,
    )
    assert published.status == KnowledgeArticleStatus.PUBLISHED.value

    response = await api_client.get(
        f"/api/v1/knowledge/articles/{article.id}",
        headers=auth_header(employee_a),
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["status"] == KnowledgeArticleStatus.PUBLISHED.value
    assert body["current_version"]["body"] == "Welcome published body"
    assert body["current_version"]["index_status"] == "indexed"
    assert body["current_version"]["indexed_at"] is not None
    assert body["current_version"]["failure_category"] is None
    assert body["current_version"]["index_stale"] is False
    assert body["current_version"]["embedding_compatible"] is True
    assert body["current_version"]["reindex_required"] is False
    assert body["current_version"]["embedding_incompatibility_reason"] is None
    assert "Welcome published body" in response.text


@pytest.mark.asyncio
async def test_employee_cannot_read_draft_article(
    api_client: AsyncClient,
    article_service: ArticleService,
    company_a: Company,
    employee_a: Employee,
) -> None:
    article = await article_service.create_article(
        company_id=company_a.id,
        actor_company_id=company_a.id,
        title="Secret draft",
        body="DRAFT_SECRET_BODY",
    )

    response = await api_client.get(
        f"/api/v1/knowledge/articles/{article.id}",
        headers=auth_header(employee_a),
    )
    assert response.status_code == 404, response.text
    assert "not found" in response.json()["detail"].lower()
    assert "DRAFT_SECRET_BODY" not in response.text


@pytest.mark.asyncio
async def test_employee_cannot_read_archived_article(
    api_client: AsyncClient,
    article_service: ArticleService,
    company_a: Company,
    employee_a: Employee,
) -> None:
    article = await article_service.create_article(
        company_id=company_a.id,
        actor_company_id=company_a.id,
        title="Archived doc",
        body="ARCHIVED_SECRET_BODY",
    )
    await article_service.publish_article(article.id, company_id=company_a.id)
    await article_service.archive_article(article.id, company_id=company_a.id)

    response = await api_client.get(
        f"/api/v1/knowledge/articles/{article.id}",
        headers=auth_header(employee_a),
    )
    assert response.status_code == 404, response.text
    assert "ARCHIVED_SECRET_BODY" not in response.text


@pytest.mark.asyncio
async def test_employee_cannot_read_other_company_article(
    api_client: AsyncClient,
    article_service: ArticleService,
    company_a: Company,
    employee_a: Employee,
    company_b: Company,
) -> None:
    article = await article_service.create_article(
        company_id=company_b.id,
        actor_company_id=company_b.id,
        title="Other tenant",
        body="OTHER_COMPANY_SECRET",
        visibility=KnowledgeVisibility.COMPANY.value,
    )
    await article_service.publish_article(article.id, company_id=company_b.id)

    response = await api_client.get(
        f"/api/v1/knowledge/articles/{article.id}",
        headers=auth_header(employee_a),
    )
    assert response.status_code == 404, response.text
    assert "OTHER_COMPANY_SECRET" not in response.text


@pytest.mark.asyncio
async def test_employee_cannot_read_program_article_for_other_program(
    api_client: AsyncClient,
    article_service: ArticleService,
    company_a: Company,
    employee_a: Employee,
) -> None:
    their_program = await _create_program(company_a.id)
    other_program = await _create_program(company_a.id)
    await _assign_employee(
        company_id=company_a.id,
        employee_id=employee_a.id,
        program_id=their_program.id,
    )

    article = await article_service.create_article(
        company_id=company_a.id,
        actor_company_id=company_a.id,
        title="Other program article",
        body="OTHER_PROGRAM_SECRET",
        visibility=KnowledgeVisibility.PROGRAM.value,
    )
    await article_service.publish_article(article.id, company_id=company_a.id)
    await _link_article_to_program(
        company_id=company_a.id,
        article_id=article.id,
        program_id=other_program.id,
    )

    response = await api_client.get(
        f"/api/v1/knowledge/articles/{article.id}",
        headers=auth_header(employee_a),
    )
    assert response.status_code == 404, response.text
    assert "OTHER_PROGRAM_SECRET" not in response.text


@pytest.mark.asyncio
async def test_employee_can_read_published_program_article_for_their_program(
    api_client: AsyncClient,
    article_service: ArticleService,
    company_a: Company,
    employee_a: Employee,
) -> None:
    program = await _create_program(company_a.id)
    await _assign_employee(
        company_id=company_a.id,
        employee_id=employee_a.id,
        program_id=program.id,
    )

    article = await article_service.create_article(
        company_id=company_a.id,
        actor_company_id=company_a.id,
        title="Program guide",
        body="PROGRAM_ALLOWED_BODY",
        visibility=KnowledgeVisibility.PROGRAM.value,
    )
    await article_service.publish_article(article.id, company_id=company_a.id)
    await _link_article_to_program(
        company_id=company_a.id,
        article_id=article.id,
        program_id=program.id,
    )

    response = await api_client.get(
        f"/api/v1/knowledge/articles/{article.id}",
        headers=auth_header(employee_a),
    )
    assert response.status_code == 200, response.text
    assert response.json()["current_version"]["body"] == "PROGRAM_ALLOWED_BODY"


@pytest.mark.asyncio
async def test_employee_cannot_read_program_article_without_links(
    api_client: AsyncClient,
    article_service: ArticleService,
    company_a: Company,
    employee_a: Employee,
) -> None:
    """visibility=program with no links fails closed for employees."""
    article = await article_service.create_article(
        company_id=company_a.id,
        actor_company_id=company_a.id,
        title="Unlinked program article",
        body="UNLINKED_SECRET",
        visibility=KnowledgeVisibility.PROGRAM.value,
    )
    await article_service.publish_article(article.id, company_id=company_a.id)

    response = await api_client.get(
        f"/api/v1/knowledge/articles/{article.id}",
        headers=auth_header(employee_a),
    )
    assert response.status_code == 404, response.text
    assert "UNLINKED_SECRET" not in response.text


@pytest.mark.asyncio
async def test_hr_can_read_draft_and_archived_articles(
    api_client: AsyncClient,
    article_service: ArticleService,
    company_a: Company,
    hr_a: Employee,
) -> None:
    draft = await article_service.create_article(
        company_id=company_a.id,
        actor_company_id=company_a.id,
        title="HR draft",
        body="HR_DRAFT_BODY",
    )
    archived = await article_service.create_article(
        company_id=company_a.id,
        actor_company_id=company_a.id,
        title="HR archive",
        body="HR_ARCHIVED_BODY",
    )
    await article_service.publish_article(archived.id, company_id=company_a.id)
    await article_service.archive_article(archived.id, company_id=company_a.id)

    draft_res = await api_client.get(
        f"/api/v1/knowledge/articles/{draft.id}",
        headers=auth_header(hr_a),
    )
    assert draft_res.status_code == 200, draft_res.text
    assert draft_res.json()["current_version"]["body"] == "HR_DRAFT_BODY"
    assert draft_res.json()["status"] == KnowledgeArticleStatus.DRAFT.value

    archived_res = await api_client.get(
        f"/api/v1/knowledge/articles/{archived.id}",
        headers=auth_header(hr_a),
    )
    assert archived_res.status_code == 200, archived_res.text
    assert archived_res.json()["current_version"]["body"] == "HR_ARCHIVED_BODY"
    assert archived_res.json()["status"] == KnowledgeArticleStatus.ARCHIVED.value


@pytest.mark.asyncio
async def test_admin_can_read_draft_article(
    api_client: AsyncClient,
    article_service: ArticleService,
    company_a: Company,
    admin_a: Employee,
) -> None:
    article = await article_service.create_article(
        company_id=company_a.id,
        actor_company_id=company_a.id,
        title="Admin draft",
        body="ADMIN_DRAFT_BODY",
    )
    response = await api_client.get(
        f"/api/v1/knowledge/articles/{article.id}",
        headers=auth_header(admin_a),
    )
    assert response.status_code == 200, response.text
    assert response.json()["current_version"]["body"] == "ADMIN_DRAFT_BODY"


@pytest.mark.asyncio
async def test_immutable_versions_intact_after_acl(
    article_service: ArticleService,
    company_a: Company,
) -> None:
    article = await article_service.create_article(
        company_id=company_a.id,
        actor_company_id=company_a.id,
        title="V1",
        body="body-v1",
    )
    v1_id = article.current_version_id
    updated = await article_service.update_article(
        article.id,
        company_id=company_a.id,
        title="V2",
        body="body-v2",
    )
    assert updated.current_version is not None
    assert updated.current_version.version == 2
    assert updated.current_version_id != v1_id

    from app.db.models.knowledge_article_version import KnowledgeArticleVersion

    async with UnitOfWork() as uow:
        await uow.enter_platform()
        old = await uow.session.get(KnowledgeArticleVersion, v1_id)
        assert old is not None
        assert old.body == "body-v1"


@pytest.mark.asyncio
async def test_unauthorized_uuid_does_not_leak_content_via_service(
    article_service: ArticleService,
    company_a: Company,
    employee_a: Employee,
) -> None:
    article = await article_service.create_article(
        company_id=company_a.id,
        actor_company_id=company_a.id,
        title="Leak check",
        body="SHOULD_NOT_LEAK",
    )
    with pytest.raises(NotFoundError, match="not found"):
        await article_service.get_article(
            article.id,
            company_id=company_a.id,
            actor_role=EmployeeRole.EMPLOYEE.value,
            actor_employee_id=employee_a.id,
        )


@pytest.mark.asyncio
async def test_cancelled_assignment_does_not_grant_program_article(
    api_client: AsyncClient,
    article_service: ArticleService,
    company_a: Company,
    employee_a: Employee,
) -> None:
    program = await _create_program(company_a.id)
    await _assign_employee(
        company_id=company_a.id,
        employee_id=employee_a.id,
        program_id=program.id,
        status=AssignmentStatus.CANCELLED.value,
    )
    article = await article_service.create_article(
        company_id=company_a.id,
        actor_company_id=company_a.id,
        title="Cancelled assignment",
        body="CANCELLED_ASSIGNMENT_SECRET",
        visibility=KnowledgeVisibility.PROGRAM.value,
    )
    await article_service.publish_article(article.id, company_id=company_a.id)
    await _link_article_to_program(
        company_id=company_a.id,
        article_id=article.id,
        program_id=program.id,
    )

    response = await api_client.get(
        f"/api/v1/knowledge/articles/{article.id}",
        headers=auth_header(employee_a),
    )
    assert response.status_code == 404, response.text
    assert "CANCELLED_ASSIGNMENT_SECRET" not in response.text


@pytest.mark.asyncio
async def test_employee_list_hides_drafts_and_unlinked_program_articles(
    api_client: AsyncClient,
    article_service: ArticleService,
    company_a: Company,
    employee_a: Employee,
    hr_a: Employee,
) -> None:
    draft = await article_service.create_article(
        company_id=company_a.id,
        actor_company_id=company_a.id,
        title="Hidden draft",
        body="DRAFT_LIST_SECRET",
    )
    published = await article_service.create_article(
        company_id=company_a.id,
        actor_company_id=company_a.id,
        title="Visible handbook",
        body="Published list body",
        visibility=KnowledgeVisibility.COMPANY.value,
    )
    await article_service.publish_article(published.id, company_id=company_a.id)

    program = await _create_program(company_a.id)
    program_article = await article_service.create_article(
        company_id=company_a.id,
        actor_company_id=company_a.id,
        title="Program only",
        body="PROGRAM_LIST_SECRET",
        visibility=KnowledgeVisibility.PROGRAM.value,
        program_ids=[program.id],
    )
    await article_service.publish_article(program_article.id, company_id=company_a.id)

    listed = await api_client.get(
        "/api/v1/knowledge/articles",
        headers=auth_header(employee_a),
        params={"company_id": str(company_a.id)},
    )
    assert listed.status_code == 200, listed.text
    titles = {
        item["current_version"]["title"]
        for item in listed.json()["items"]
        if item.get("current_version")
    }
    assert "Visible handbook" in titles
    assert "Hidden draft" not in titles
    assert "Program only" not in titles
    assert "DRAFT_LIST_SECRET" not in listed.text
    assert "PROGRAM_LIST_SECRET" not in listed.text

    hr_list = await api_client.get(
        "/api/v1/knowledge/articles",
        headers=auth_header(hr_a),
        params={"company_id": str(company_a.id), "status": "draft"},
    )
    assert hr_list.status_code == 200, hr_list.text
    hr_ids = {item["id"] for item in hr_list.json()["items"]}
    assert str(draft.id) in hr_ids

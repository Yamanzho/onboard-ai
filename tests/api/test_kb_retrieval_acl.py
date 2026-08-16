"""ACL-first retrieval: ArticleService visibility, tenant RLS, UUID probing."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text

from app.core.exceptions import ForbiddenError, NotFoundError
from app.db.enums import (
    AssignmentStatus,
    EmployeeRole,
    KnowledgeVisibility,
    PlatformRole,
)
from app.db.models.assignment import Assignment
from app.db.models.company import Company
from app.db.models.employee import Employee
from app.db.models.onboarding_program import OnboardingProgram
from app.db.uow import UnitOfWork
from app.services.ai.embeddings import FakeEmbeddingProvider
from app.services.ai.retriever import KnowledgeRetriever
from app.services.knowledge.article_service import ArticleService
from tests.conftest import _uow_factory


@pytest.fixture
def retriever(article_service: ArticleService) -> KnowledgeRetriever:
    return KnowledgeRetriever(
        uow_factory=_uow_factory,
        article_service=article_service,
        embedding_provider=FakeEmbeddingProvider(),
    )


async def _create_program(company_id: UUID) -> OnboardingProgram:
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
    company_id: UUID,
    employee_id: UUID,
    program_id: UUID,
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


async def _publish(
    article_service: ArticleService,
    company: Company,
    *,
    title: str,
    body: str,
    visibility: str = KnowledgeVisibility.COMPANY.value,
    program_ids: list[UUID] | None = None,
):
    article = await article_service.create_article(
        company_id=company.id,
        actor_company_id=company.id,
        title=title,
        body=body,
        visibility=visibility,
        program_ids=program_ids,
    )
    return await article_service.publish_article(article.id, company_id=company.id)


async def test_company_visible_article_is_retrievable(
    article_service: ArticleService,
    retriever: KnowledgeRetriever,
    company_a: Company,
    employee_a: Employee,
) -> None:
    token = f"COMPANY_VISIBLE_{uuid4().hex}"
    article = await _publish(
        article_service, company_a, title="Company handbook", body=token
    )
    hits = await retriever.retrieve(
        token,
        actor_company_id=company_a.id,
        actor_employee_id=employee_a.id,
        actor_role=EmployeeRole.EMPLOYEE.value,
    )
    assert any(h.article_id == article.id and token in h.content for h in hits)


async def test_other_company_article_is_not_retrievable(
    article_service: ArticleService,
    retriever: KnowledgeRetriever,
    company_a: Company,
    company_b: Company,
    employee_a: Employee,
) -> None:
    token = f"TENANT_B_SECRET_{uuid4().hex}"
    article_b = await _publish(
        article_service, company_b, title="B handbook", body=token
    )
    hits = await retriever.retrieve(
        token,
        actor_company_id=company_a.id,
        actor_employee_id=employee_a.id,
        actor_role=EmployeeRole.EMPLOYEE.value,
    )
    assert all(h.article_id != article_b.id for h in hits)
    assert all(token not in h.content for h in hits)


async def test_program_visible_assigned_employee_can_retrieve(
    article_service: ArticleService,
    retriever: KnowledgeRetriever,
    company_a: Company,
    employee_a: Employee,
) -> None:
    program = await _create_program(company_a.id)
    await _assign_employee(
        company_id=company_a.id,
        employee_id=employee_a.id,
        program_id=program.id,
    )
    token = f"PROGRAM_OK_{uuid4().hex}"
    article = await _publish(
        article_service,
        company_a,
        title="Program guide",
        body=token,
        visibility=KnowledgeVisibility.PROGRAM.value,
        program_ids=[program.id],
    )
    hits = await retriever.retrieve(
        token,
        actor_company_id=company_a.id,
        actor_employee_id=employee_a.id,
        actor_role=EmployeeRole.EMPLOYEE.value,
    )
    assert any(h.article_id == article.id for h in hits)


async def test_program_visible_unassigned_employee_cannot_retrieve(
    article_service: ArticleService,
    retriever: KnowledgeRetriever,
    company_a: Company,
    employee_a: Employee,
) -> None:
    program = await _create_program(company_a.id)
    token = f"PROGRAM_DENIED_{uuid4().hex}"
    article = await _publish(
        article_service,
        company_a,
        title="Other program",
        body=token,
        visibility=KnowledgeVisibility.PROGRAM.value,
        program_ids=[program.id],
    )
    hits = await retriever.retrieve(
        token,
        actor_company_id=company_a.id,
        actor_employee_id=employee_a.id,
        actor_role=EmployeeRole.EMPLOYEE.value,
    )
    assert all(h.article_id != article.id for h in hits)
    assert all(token not in h.content for h in hits)


async def test_cancelled_assignment_does_not_grant_retrieval(
    article_service: ArticleService,
    retriever: KnowledgeRetriever,
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
    token = f"CANCELLED_KB_{uuid4().hex}"
    article = await _publish(
        article_service,
        company_a,
        title="Cancelled program KB",
        body=token,
        visibility=KnowledgeVisibility.PROGRAM.value,
        program_ids=[program.id],
    )
    hits = await retriever.retrieve(
        token,
        actor_company_id=company_a.id,
        actor_employee_id=employee_a.id,
        actor_role=EmployeeRole.EMPLOYEE.value,
    )
    assert all(h.article_id != article.id for h in hits)


async def test_employee_cannot_retrieve_hr_visible_draft(
    article_service: ArticleService,
    retriever: KnowledgeRetriever,
    company_a: Company,
    employee_a: Employee,
    hr_a: Employee,
) -> None:
    """No HR-only visibility enum exists; drafts are HR-readable, not retrievable."""
    token = f"HR_DRAFT_{uuid4().hex}"
    draft = await article_service.create_article(
        company_id=company_a.id,
        actor_company_id=company_a.id,
        title="HR draft",
        body=token,
    )
    listed = await article_service.list_articles(
        company_a.id,
        actor_company_id=company_a.id,
        actor_role=EmployeeRole.HR.value,
        actor_employee_id=hr_a.id,
    )
    assert any(row.id == draft.id for row in listed)

    hits = await retriever.retrieve(
        token,
        actor_company_id=company_a.id,
        actor_employee_id=employee_a.id,
        actor_role=EmployeeRole.EMPLOYEE.value,
    )
    assert all(token not in h.content for h in hits)

    hr_hits = await retriever.retrieve(
        token,
        actor_company_id=company_a.id,
        actor_employee_id=hr_a.id,
        actor_role=EmployeeRole.HR.value,
    )
    assert all(token not in h.content for h in hr_hits)


async def test_uuid_probing_does_not_bypass_acl(
    article_service: ArticleService,
    retriever: KnowledgeRetriever,
    company_a: Company,
    company_b: Company,
    employee_a: Employee,
) -> None:
    token = f"PROBE_B_{uuid4().hex}"
    article_b = await _publish(article_service, company_b, title="Secret B", body=token)
    assert article_b.current_version_id is not None

    hits = await retriever.retrieve(
        token,
        actor_company_id=company_a.id,
        actor_employee_id=employee_a.id,
        actor_role=EmployeeRole.EMPLOYEE.value,
        claimed_company_id=company_a.id,
    )
    assert hits == [] or all(h.article_id != article_b.id for h in hits)

    with pytest.raises(NotFoundError):
        await retriever.retrieve(
            token,
            actor_company_id=company_a.id,
            actor_employee_id=employee_a.id,
            actor_role=EmployeeRole.EMPLOYEE.value,
            claimed_company_id=company_b.id,
        )


async def test_rls_blocks_cross_tenant_similarity_even_if_ids_are_passed(
    article_service: ArticleService,
    company_a: Company,
    company_b: Company,
) -> None:
    token = f"RLS_B_{uuid4().hex}"
    article_b = await _publish(article_service, company_b, title="B rls", body=token)
    assert article_b.current_version_id is not None
    query_vec = await FakeEmbeddingProvider().embed(token)

    async with UnitOfWork() as uow:
        await uow.enter_tenant(company_a.id)
        leaked = await uow.knowledge_article_chunks.search_similar_current_published(
            allowed_article_ids=[article_b.id],
            query_embedding=query_vec,
            limit=20,
        )
        raw = await uow.session.execute(
            text("SELECT id FROM knowledge_article_chunks WHERE article_id = :id"),
            {"id": article_b.id},
        )
    assert leaked == []
    assert raw.first() is None


async def test_retriever_cross_tenant_query_matching_b_content(
    article_service: ArticleService,
    retriever: KnowledgeRetriever,
    company_a: Company,
    company_b: Company,
    employee_a: Employee,
) -> None:
    token = f"MATCH_B_{uuid4().hex}"
    await _publish(article_service, company_a, title="A decoy", body="unrelated A")
    await _publish(article_service, company_b, title="B match", body=token)
    hits = await retriever.retrieve(
        token,
        actor_company_id=company_a.id,
        actor_employee_id=employee_a.id,
        actor_role=EmployeeRole.EMPLOYEE.value,
    )
    assert all(token not in h.content for h in hits)
    assert all(h.article_title != "B match" for h in hits)


async def test_super_admin_forbidden_on_acl_path(
    retriever: KnowledgeRetriever,
    company_a: Company,
    employee_a: Employee,
) -> None:
    with pytest.raises(ForbiddenError, match="Super Admin"):
        await retriever.retrieve(
            "kb",
            actor_company_id=company_a.id,
            actor_employee_id=employee_a.id,
            actor_role=PlatformRole.SUPER_ADMIN.value,
        )

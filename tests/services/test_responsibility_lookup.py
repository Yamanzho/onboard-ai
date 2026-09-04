"""Phase 9B: ResponsibilityLookupService is pure DB lookup (no LLM)."""

from __future__ import annotations

from uuid import uuid4

from app.db.models.company import Company
from app.db.models.department import Department
from app.db.models.employee import Employee
from app.db.models.question_topic import QuestionTopic
from app.db.models.topic_responsibility import TopicResponsibility
from app.services.responsibility import ResponsibilityLookupService
from tests.conftest import _uow_factory


async def _seed_topic(
    company_id,
    *,
    slug: str = "vacation",
    is_active: bool = True,
    with_mapping: bool = True,
    employee_id=None,
) -> tuple[QuestionTopic, Department | None]:
    async with _uow_factory() as uow:
        await uow.enter_platform()
        department = await uow.departments.create(
            Department(
                company_id=company_id,
                name="HR",
                slug=f"hr-{uuid4().hex[:8]}",
                is_active=True,
            ),
        )
        topic = await uow.question_topics.create(
            QuestionTopic(
                company_id=company_id,
                name="Vacation",
                slug=slug,
                is_active=is_active,
            ),
        )
        if with_mapping:
            await uow.topic_responsibilities.create(
                TopicResponsibility(
                    company_id=company_id,
                    topic_id=topic.id,
                    department_id=department.id,
                    employee_id=employee_id,
                ),
            )
        await uow.commit()
        return topic, department


async def test_lookup_success_by_id_and_slug(
    company_a: Company,
    employee_a: Employee,
) -> None:
    topic, department = await _seed_topic(
        company_a.id,
        slug="vacation",
        employee_id=employee_a.id,
    )
    service = ResponsibilityLookupService()
    by_id = await service.lookup(company_a.id, topic_id=topic.id)
    assert by_id is not None
    assert by_id.topic_slug == "vacation"
    assert by_id.department_id == department.id
    assert by_id.department_name == "HR"
    assert by_id.employee_id == employee_a.id
    assert by_id.employee_full_name == employee_a.full_name

    by_slug = await service.lookup(company_a.id, topic_slug="vacation")
    assert by_slug is not None
    assert by_slug.topic_id == topic.id


async def test_lookup_missing_or_unconfigured_returns_none(company_a: Company) -> None:
    service = ResponsibilityLookupService()
    assert await service.lookup(company_a.id, topic_id=uuid4()) is None
    assert await service.lookup(company_a.id, topic_slug="does-not-exist") is None

    topic, _ = await _seed_topic(company_a.id, slug="no-owner", with_mapping=False)
    assert await service.lookup(company_a.id, topic_id=topic.id) is None


async def test_lookup_inactive_topic_returns_none(company_a: Company) -> None:
    topic, _ = await _seed_topic(company_a.id, slug="old", is_active=False)
    service = ResponsibilityLookupService()
    assert await service.lookup(company_a.id, topic_id=topic.id) is None
    assert await service.lookup(company_a.id, topic_slug="old") is None


async def test_lookup_does_not_leak_other_tenant(
    company_a: Company,
    company_b: Company,
) -> None:
    topic, _ = await _seed_topic(company_b.id, slug="secret")
    service = ResponsibilityLookupService()
    assert await service.lookup(company_a.id, topic_id=topic.id) is None
    assert await service.lookup(company_a.id, topic_slug="secret") is None

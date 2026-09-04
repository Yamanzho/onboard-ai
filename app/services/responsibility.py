"""Pure DB lookup of configured topic responsibility. No LLM. No chat wiring."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from uuid import UUID

from app.core.exceptions import ValidationError
from app.db.uow import UnitOfWork


@dataclass(frozen=True, slots=True)
class ResponsibilityResult:
    topic_id: UUID
    topic_name: str
    topic_slug: str
    department_id: UUID | None
    department_name: str | None
    department_slug: str | None
    employee_id: UUID | None
    employee_full_name: str | None
    employee_job_title: str | None


class ResponsibilityLookupService:
    """Read-only structured lookup for Phase 9I to call later."""

    def __init__(self, uow_factory: Callable[[], UnitOfWork] | None = None) -> None:
        self._uow_factory = uow_factory or UnitOfWork

    async def lookup(
        self,
        company_id: UUID,
        *,
        topic_id: UUID | None = None,
        topic_slug: str | None = None,
    ) -> ResponsibilityResult | None:
        if topic_id is None and not (isinstance(topic_slug, str) and topic_slug.strip()):
            raise ValidationError("topic_id or topic_slug is required")

        async with self._uow_factory() as uow:
            await uow.enter_tenant(company_id)
            if topic_id is not None:
                topic = await uow.question_topics.get_by_id_with_responsibility(topic_id)
            else:
                topic = await uow.question_topics.get_by_slug(
                    company_id,
                    topic_slug.strip(),  # type: ignore[union-attr]
                )
            if topic is None or topic.company_id != company_id:
                return None
            if not topic.is_active:
                return None
            mapping = await uow.topic_responsibilities.get_by_topic_id(topic.id)
            if mapping is None:
                return None
            department = mapping.department
            employee = mapping.employee
            return ResponsibilityResult(
                topic_id=topic.id,
                topic_name=topic.name,
                topic_slug=topic.slug,
                department_id=mapping.department_id,
                department_name=department.name if department is not None else None,
                department_slug=department.slug if department is not None else None,
                employee_id=mapping.employee_id,
                employee_full_name=employee.full_name if employee is not None else None,
                employee_job_title=employee.job_title if employee is not None else None,
            )

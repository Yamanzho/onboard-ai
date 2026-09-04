from collections.abc import Callable
from typing import Any
from uuid import UUID

from sqlalchemy.exc import IntegrityError

from app.core.exceptions import ConflictError, NotFoundError, ValidationError
from app.db.enums import CompanyAuditAction
from app.db.models.question_topic import QuestionTopic
from app.db.models.topic_responsibility import TopicResponsibility
from app.db.uow import UnitOfWork
from app.services.company_audit import record_company_audit
from app.services.knowledge._slug import slugify
from app.services.org_validation import (
    resolve_department_for_assignment,
    resolve_employee_for_assignment,
)
from app.services.tenancy import ensure_same_company


class QuestionTopicService:
    """Application service for question topics and responsibility mappings."""

    def __init__(self, uow_factory: Callable[[], UnitOfWork] | None = None) -> None:
        self._uow_factory = uow_factory or UnitOfWork

    async def create_topic(
        self,
        *,
        company_id: UUID,
        actor_company_id: UUID,
        name: str,
        slug: str | None = None,
        description: str | None = None,
        is_active: bool = True,
        department_id: UUID | None = None,
        employee_id: UUID | None = None,
        actor_employee_id: UUID | None = None,
    ) -> QuestionTopic:
        ensure_same_company(
            resource_company_id=company_id,
            actor_company_id=actor_company_id,
            not_found_message=f"Company {company_id} not found",
        )
        try:
            resolved_slug = slug or slugify(name)
        except ValueError as exc:
            raise ValidationError(str(exc)) from exc

        async with self._uow_factory() as uow:
            await uow.enter_tenant(company_id)
            company = await uow.companies.get_by_id(company_id)
            if company is None:
                raise NotFoundError(f"Company {company_id} not found")
            if department_id is not None:
                await resolve_department_for_assignment(
                    uow,
                    department_id=department_id,
                    company_id=company_id,
                )
            if employee_id is not None:
                await resolve_employee_for_assignment(
                    uow,
                    employee_id=employee_id,
                    company_id=company_id,
                )
            try:
                topic = await uow.question_topics.create(
                    QuestionTopic(
                        company_id=company_id,
                        name=name.strip(),
                        slug=resolved_slug,
                        description=description.strip() if description else None,
                        is_active=is_active,
                    ),
                )
                if department_id is not None or employee_id is not None:
                    await uow.topic_responsibilities.create(
                        TopicResponsibility(
                            company_id=company_id,
                            topic_id=topic.id,
                            department_id=department_id,
                            employee_id=employee_id,
                        ),
                    )
                await record_company_audit(
                    uow,
                    company_id=company_id,
                    actor_employee_id=actor_employee_id,
                    action=CompanyAuditAction.TOPIC_CREATED.value,
                    resource_type="topic",
                    resource_id=topic.id,
                    summary=f"Created topic {topic.name!r}",
                    details={"slug": topic.slug},
                )
                await uow.commit()
            except IntegrityError as exc:
                await uow.rollback()
                raise ConflictError(
                    f"Topic slug {resolved_slug!r} already exists in company {company_id}"
                ) from exc
            return await self.get_topic(topic.id, company_id=company_id)

    async def get_topic(
        self,
        topic_id: UUID,
        *,
        company_id: UUID,
    ) -> QuestionTopic:
        async with self._uow_factory() as uow:
            await uow.enter_tenant(company_id)
            topic = await uow.question_topics.get_by_id_with_responsibility(topic_id)
            if topic is None:
                raise NotFoundError(f"Question topic {topic_id} not found")
            ensure_same_company(
                resource_company_id=topic.company_id,
                actor_company_id=company_id,
                not_found_message=f"Question topic {topic_id} not found",
            )
            return topic

    async def list_topics(
        self,
        company_id: UUID,
        *,
        actor_company_id: UUID,
        is_active: bool | None = None,
        offset: int = 0,
        limit: int = 100,
    ) -> list[QuestionTopic]:
        ensure_same_company(
            resource_company_id=company_id,
            actor_company_id=actor_company_id,
            not_found_message=f"Company {company_id} not found",
        )
        async with self._uow_factory() as uow:
            await uow.enter_tenant(company_id)
            company = await uow.companies.get_by_id(company_id)
            if company is None:
                raise NotFoundError(f"Company {company_id} not found")
            return await uow.question_topics.list_by_company_id(
                company_id,
                is_active=is_active,
                offset=offset,
                limit=limit,
            )

    async def update_topic(
        self,
        topic_id: UUID,
        *,
        company_id: UUID,
        actor_employee_id: UUID | None = None,
        **values: Any,
    ) -> QuestionTopic:
        forbidden = {"id", "company_id", "created_at"}
        extra = forbidden.intersection(values)
        if extra:
            raise ValidationError(
                f"Cannot update fields via update_topic: {sorted(extra)}"
            )
        if "name" in values and isinstance(values["name"], str):
            values["name"] = values["name"].strip()
        if "description" in values and isinstance(values["description"], str):
            stripped = values["description"].strip()
            values["description"] = stripped or None

        async with self._uow_factory() as uow:
            await uow.enter_tenant(company_id)
            topic = await uow.question_topics.get_by_id(topic_id)
            if topic is None:
                raise NotFoundError(f"Question topic {topic_id} not found")
            ensure_same_company(
                resource_company_id=topic.company_id,
                actor_company_id=company_id,
                not_found_message=f"Question topic {topic_id} not found",
            )
            try:
                updated = await uow.question_topics.update(topic_id, **values)
                if updated is None:
                    raise NotFoundError(f"Question topic {topic_id} not found")
                await record_company_audit(
                    uow,
                    company_id=company_id,
                    actor_employee_id=actor_employee_id,
                    action=CompanyAuditAction.TOPIC_UPDATED.value,
                    resource_type="topic",
                    resource_id=topic_id,
                    summary=f"Updated topic {updated.name!r}",
                    details={"fields": sorted(str(key) for key in values)},
                )
                await uow.commit()
            except IntegrityError as exc:
                await uow.rollback()
                raise ConflictError(
                    f"Topic slug already exists in company {company_id}"
                ) from exc
            return await self.get_topic(topic_id, company_id=company_id)

    async def set_responsibility(
        self,
        topic_id: UUID,
        *,
        company_id: UUID,
        department_id: UUID | None,
        employee_id: UUID | None,
        actor_employee_id: UUID | None = None,
    ) -> QuestionTopic:
        if department_id is None and employee_id is None:
            raise ValidationError("department_id or employee_id is required")

        async with self._uow_factory() as uow:
            await uow.enter_tenant(company_id)
            topic = await uow.question_topics.get_by_id(topic_id)
            if topic is None:
                raise NotFoundError(f"Question topic {topic_id} not found")
            ensure_same_company(
                resource_company_id=topic.company_id,
                actor_company_id=company_id,
                not_found_message=f"Question topic {topic_id} not found",
            )
            if department_id is not None:
                await resolve_department_for_assignment(
                    uow,
                    department_id=department_id,
                    company_id=company_id,
                )
            if employee_id is not None:
                await resolve_employee_for_assignment(
                    uow,
                    employee_id=employee_id,
                    company_id=company_id,
                )
            existing = await uow.topic_responsibilities.get_by_topic_id(topic_id)
            try:
                if existing is None:
                    await uow.topic_responsibilities.create(
                        TopicResponsibility(
                            company_id=company_id,
                            topic_id=topic_id,
                            department_id=department_id,
                            employee_id=employee_id,
                        ),
                    )
                else:
                    await uow.topic_responsibilities.update(
                        existing.id,
                        department_id=department_id,
                        employee_id=employee_id,
                    )
                await record_company_audit(
                    uow,
                    company_id=company_id,
                    actor_employee_id=actor_employee_id,
                    action=CompanyAuditAction.TOPIC_RESPONSIBILITY_CHANGED.value,
                    resource_type="topic",
                    resource_id=topic_id,
                    summary=f"Updated responsibility for topic {topic.name!r}",
                    details={
                        "department_id": str(department_id) if department_id else None,
                        "employee_id": str(employee_id) if employee_id else None,
                    },
                )
                await uow.commit()
            except IntegrityError as exc:
                await uow.rollback()
                raise ConflictError(
                    "Identical topic responsibility mapping already exists"
                ) from exc
            return await self.get_topic(topic_id, company_id=company_id)

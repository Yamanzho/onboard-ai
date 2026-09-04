from collections.abc import Callable
from typing import Any
from uuid import UUID

from sqlalchemy.exc import IntegrityError

from app.core.exceptions import ConflictError, NotFoundError, ValidationError
from app.db.enums import CompanyAuditAction
from app.db.models.department import Department
from app.db.uow import UnitOfWork
from app.services.company_audit import record_company_audit
from app.services.knowledge._slug import slugify
from app.services.tenancy import ensure_same_company


class DepartmentService:
    """Application service for tenant departments."""

    def __init__(self, uow_factory: Callable[[], UnitOfWork] | None = None) -> None:
        self._uow_factory = uow_factory or UnitOfWork

    async def create_department(
        self,
        *,
        company_id: UUID,
        actor_company_id: UUID,
        name: str,
        slug: str | None = None,
        description: str | None = None,
        is_active: bool = True,
        actor_employee_id: UUID | None = None,
    ) -> Department:
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
            try:
                department = await uow.departments.create(
                    Department(
                        company_id=company_id,
                        name=name.strip(),
                        slug=resolved_slug,
                        description=description.strip() if description else None,
                        is_active=is_active,
                    ),
                )
                await record_company_audit(
                    uow,
                    company_id=company_id,
                    actor_employee_id=actor_employee_id,
                    action=CompanyAuditAction.DEPARTMENT_CREATED.value,
                    resource_type="department",
                    resource_id=department.id,
                    summary=f"Created department {department.name!r}",
                    details={"slug": department.slug},
                )
                await uow.commit()
            except IntegrityError as exc:
                await uow.rollback()
                raise ConflictError(
                    f"Department slug {resolved_slug!r} already exists "
                    f"in company {company_id}"
                ) from exc
            return department

    async def get_department(
        self,
        department_id: UUID,
        *,
        company_id: UUID,
    ) -> Department:
        async with self._uow_factory() as uow:
            await uow.enter_tenant(company_id)
            department = await uow.departments.get_by_id(department_id)
            if department is None:
                raise NotFoundError(f"Department {department_id} not found")
            ensure_same_company(
                resource_company_id=department.company_id,
                actor_company_id=company_id,
                not_found_message=f"Department {department_id} not found",
            )
            return department

    async def list_departments(
        self,
        company_id: UUID,
        *,
        actor_company_id: UUID,
        is_active: bool | None = None,
        offset: int = 0,
        limit: int = 100,
    ) -> list[Department]:
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
            return await uow.departments.list_by_company_id(
                company_id,
                is_active=is_active,
                offset=offset,
                limit=limit,
            )

    async def update_department(
        self,
        department_id: UUID,
        *,
        company_id: UUID,
        actor_employee_id: UUID | None = None,
        **values: Any,
    ) -> Department:
        forbidden = {"id", "company_id", "created_at"}
        extra = forbidden.intersection(values)
        if extra:
            raise ValidationError(
                f"Cannot update fields via update_department: {sorted(extra)}"
            )
        if "name" in values and isinstance(values["name"], str):
            values["name"] = values["name"].strip()
        if "description" in values and isinstance(values["description"], str):
            stripped = values["description"].strip()
            values["description"] = stripped or None
        if "slug" in values and values["slug"] is None:
            raise ValidationError("slug cannot be empty")

        async with self._uow_factory() as uow:
            await uow.enter_tenant(company_id)
            department = await uow.departments.get_by_id(department_id)
            if department is None:
                raise NotFoundError(f"Department {department_id} not found")
            ensure_same_company(
                resource_company_id=department.company_id,
                actor_company_id=company_id,
                not_found_message=f"Department {department_id} not found",
            )
            try:
                updated = await uow.departments.update(department_id, **values)
                if updated is None:
                    raise NotFoundError(f"Department {department_id} not found")
                await record_company_audit(
                    uow,
                    company_id=company_id,
                    actor_employee_id=actor_employee_id,
                    action=CompanyAuditAction.DEPARTMENT_UPDATED.value,
                    resource_type="department",
                    resource_id=department_id,
                    summary=f"Updated department {updated.name!r}",
                    details={"fields": sorted(str(key) for key in values)},
                )
                await uow.commit()
            except IntegrityError as exc:
                await uow.rollback()
                raise ConflictError(
                    f"Department slug already exists in company {company_id}"
                ) from exc
            return updated

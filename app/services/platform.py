"""Platform Super Admin application services (cross-tenant, no company scope)."""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.core.exceptions import ConflictError, NotFoundError, ValidationError
from app.core.security import hash_password, verify_password
from app.db.enums import (
    AssignmentStatus,
    EmployeeRole,
    EmployeeStatus,
    PaymentStatus,
    PlatformAuditAction,
    PlatformRole,
    SubscriptionHistoryEventType,
    SubscriptionStatus,
    SubscriptionTier,
)
from app.db.models.assignment import Assignment
from app.db.models.company import Company
from app.db.models.company_subscription import CompanySubscription
from app.db.models.employee import Employee
from app.db.models.knowledge_article import KnowledgeArticle
from app.db.models.onboarding_program import OnboardingProgram
from app.db.models.platform_audit_log import PlatformAuditLog
from app.db.models.super_admin import SuperAdmin
from app.db.uow import UnitOfWork
from app.schemas.super_admin import (
    CompanyLimitsResponse,
    CompanySubscriptionResponse,
    CompanySubscriptionUpdate,
    CompanyUserCreate,
    InviteAcceptRequest,
    InvitePreviewResponse,
    PlatformAuditLogResponse,
    PlatformDashboardStats,
    PlatformSettingsResponse,
    PlatformSettingsUpdate,
    PlatformUserResponse,
    SubscriptionHistoryResponse,
    SuperAdminCompanyDetail,
    SuperAdminCompanyProfileUpdate,
)
from app.services.platform_management import (
    InviteService,
    PlatformAuditMixin,
    SubscriptionMixin,
    tier_limits,
)

_PLATFORM_SETTINGS = PlatformSettingsResponse()
_MANAGEMENT_ROLES = frozenset({EmployeeRole.ADMIN.value, EmployeeRole.HR.value})
_COMPANY_ROLES = frozenset(
    {EmployeeRole.ADMIN.value, EmployeeRole.HR.value, EmployeeRole.EMPLOYEE.value}
)
_ACTIVE_ASSIGNMENT_STATUSES = frozenset(
    {AssignmentStatus.PENDING.value, AssignmentStatus.IN_PROGRESS.value}
)


class SuperAdminAuthService:
    """Authenticate and load platform Super Admins."""

    def __init__(self, uow_factory: Callable[[], UnitOfWork] | None = None) -> None:
        self._uow_factory = uow_factory or UnitOfWork

    async def authenticate(self, *, email: str, password: str) -> SuperAdmin:
        async with self._uow_factory() as uow:
            admin = await uow.super_admins.get_by_email(email.strip().lower())
            if admin is None or not verify_password(password, admin.password_hash):
                raise NotFoundError("Invalid credentials")
            if not admin.is_active:
                raise ValidationError("Super Admin account is disabled")
            return admin

    async def get_by_id(self, admin_id: UUID) -> SuperAdmin:
        async with self._uow_factory() as uow:
            admin = await uow.super_admins.get_by_id(admin_id)
            if admin is None:
                raise NotFoundError(f"Super Admin {admin_id} not found")
            if not admin.is_active:
                raise ValidationError("Super Admin account is disabled")
            return admin

    async def ensure_bootstrap_admin(
        self,
        *,
        email: str,
        password: str,
        full_name: str,
    ) -> SuperAdmin:
        normalized = email.strip().lower()
        async with self._uow_factory() as uow:
            existing = await uow.super_admins.get_by_email(normalized)
            if existing is not None:
                return existing
            admin = await uow.super_admins.create(
                SuperAdmin(
                    email=normalized,
                    full_name=full_name,
                    password_hash=hash_password(password),
                    is_active=True,
                ),
            )
            await uow.commit()
            return admin


class PlatformService(PlatformAuditMixin, SubscriptionMixin):
    """Cross-tenant operations for Super Admin panel."""

    def __init__(
        self,
        uow_factory: Callable[[], UnitOfWork] | None = None,
        invite_service: InviteService | None = None,
    ) -> None:
        self._uow_factory = uow_factory or UnitOfWork
        self._invites = invite_service or InviteService(uow_factory=self._uow_factory)

    async def get_dashboard_stats(self) -> PlatformDashboardStats:
        async with self._uow_factory() as uow:
            companies_count = await uow.session.scalar(
                select(func.count()).select_from(Company)
            )
            employees_count = await uow.session.scalar(
                select(func.count()).select_from(Employee)
            )
            active_companies = await uow.session.scalar(
                select(func.count())
                .select_from(CompanySubscription)
                .where(
                    CompanySubscription.is_current.is_(True),
                    CompanySubscription.status.in_(
                        [SubscriptionStatus.TRIAL.value, SubscriptionStatus.ACTIVE.value]
                    ),
                )
            )
            trial_companies = await uow.session.scalar(
                select(func.count())
                .select_from(CompanySubscription)
                .where(
                    CompanySubscription.is_current.is_(True),
                    CompanySubscription.status == SubscriptionStatus.TRIAL.value,
                )
            )
            expired_companies = await uow.session.scalar(
                select(func.count())
                .select_from(CompanySubscription)
                .where(
                    CompanySubscription.is_current.is_(True),
                    CompanySubscription.status.in_(
                        [
                            SubscriptionStatus.EXPIRED.value,
                            SubscriptionStatus.BLOCKED.value,
                        ]
                    ),
                )
            )
            active_assignments = await uow.session.scalar(
                select(func.count())
                .select_from(Assignment)
                .where(Assignment.status.in_(sorted(_ACTIVE_ASSIGNMENT_STATUSES)))
            )
            return PlatformDashboardStats(
                companies_count=int(companies_count or 0),
                active_companies=int(active_companies or 0),
                trial_companies=int(trial_companies or 0),
                expired_companies=int(expired_companies or 0),
                employees_count=int(employees_count or 0),
                active_assignments_count=int(active_assignments or 0),
            )

    async def list_companies(
        self,
        *,
        offset: int = 0,
        limit: int = 100,
        is_active: bool | None = None,
    ) -> list[Company]:
        async with self._uow_factory() as uow:
            stmt = select(Company).order_by(Company.created_at.desc())
            if is_active is not None:
                stmt = stmt.where(Company.is_active.is_(is_active))
            stmt = stmt.offset(offset).limit(limit)
            result = await uow.session.scalars(stmt)
            return list(result.all())

    async def get_company(self, company_id: UUID) -> SuperAdminCompanyDetail:
        async with self._uow_factory() as uow:
            company = await uow.companies.get_by_id(company_id)
            if company is None:
                raise NotFoundError(f"Company {company_id} not found")
            usage = await self._usage_counts(uow, company_id)
            subscription = await uow.company_subscriptions.get_current_for_company(company_id)
            if subscription is None:
                subscription = await self._create_subscription(uow, company_id=company_id)
                await uow.commit()
            return SuperAdminCompanyDetail(
                id=company.id,
                name=company.name,
                slug=company.slug,
                timezone=company.timezone,
                is_active=company.is_active,
                settings=company.settings or {},
                description=company.description,
                logo_url=company.logo_url,
                contact_email=company.contact_email,
                contact_phone=company.contact_phone,
                contact_person=company.contact_person,
                created_at=company.created_at,
                updated_at=company.updated_at,
                employees_count=usage["employees_count"],
                programs_count=usage["programs_count"],
                assignments_count=usage["assignments_count"],
                subscription=(
                    self._subscription_response(subscription) if subscription else None
                ),
                limits=await self._limits_response(uow, company_id, subscription, usage),
            )

    async def create_company_with_admin(
        self,
        *,
        name: str,
        slug: str,
        timezone: str = "UTC",
        settings: dict[str, Any] | None = None,
        admin_full_name: str,
        admin_email: str | None,
        admin_telegram_user_id: int,
        super_admin_id: UUID | None = None,
        description: str | None = None,
        contact_email: str | None = None,
        contact_phone: str | None = None,
        contact_person: str | None = None,
        logo_url: str | None = None,
    ) -> tuple[Company, Employee]:
        if admin_telegram_user_id <= 0:
            raise ValidationError("admin_telegram_user_id must be a positive integer")
        if not admin_email:
            raise ValidationError("admin_email is required to send an invite")

        async with self._uow_factory() as uow:
            try:
                company = await uow.companies.create(
                    Company(
                        name=name,
                        slug=slug,
                        timezone=timezone,
                        is_active=True,
                        settings=settings if settings is not None else {},
                        description=description,
                        logo_url=logo_url,
                        contact_email=contact_email,
                        contact_phone=contact_phone,
                        contact_person=contact_person,
                    ),
                )
                admin = await uow.employees.create(
                    Employee(
                        company_id=company.id,
                        telegram_user_id=admin_telegram_user_id,
                        full_name=admin_full_name,
                        email=admin_email.strip().lower(),
                        role=EmployeeRole.ADMIN.value,
                        status=EmployeeStatus.INVITED.value,
                    ),
                )
                await self._create_subscription(
                    uow,
                    company_id=company.id,
                    super_admin_id=super_admin_id,
                )
                await self._record_audit(
                    uow,
                    super_admin_id=super_admin_id,
                    action=PlatformAuditAction.COMPANY_CREATED.value,
                    resource_type="company",
                    resource_id=company.id,
                    company_id=company.id,
                    summary=f"Created company {company.name}",
                    details={"slug": company.slug},
                )
                await uow.commit()
            except IntegrityError as exc:
                await uow.rollback()
                raise ConflictError(
                    "Company slug or admin telegram_user_id already exists"
                ) from exc

        await self._invites.create_and_send_invite(
            employee=admin,
            invited_email=admin_email,
            company_name=company.name,
            super_admin_id=super_admin_id,
        )
        return company, admin

    async def update_company(self, company_id: UUID, **values: Any) -> Company:
        if not values:
            async with self._uow_factory() as uow:
                company = await uow.companies.get_by_id(company_id)
                if company is None:
                    raise NotFoundError(f"Company {company_id} not found")
                return company

        async with self._uow_factory() as uow:
            company = await uow.companies.get_by_id(company_id)
            if company is None:
                raise NotFoundError(f"Company {company_id} not found")
            try:
                updated = await uow.companies.update(company_id, **values)
                if updated is None:
                    raise NotFoundError(f"Company {company_id} not found")
                await uow.commit()
            except IntegrityError as exc:
                await uow.rollback()
                raise ConflictError("Company with this slug already exists") from exc
            return updated

    async def update_company_profile(
        self,
        company_id: UUID,
        payload: SuperAdminCompanyProfileUpdate,
        *,
        super_admin_id: UUID | None = None,
    ) -> SuperAdminCompanyDetail:
        values = payload.model_dump(exclude_unset=True)
        async with self._uow_factory() as uow:
            company = await uow.companies.get_by_id(company_id)
            if company is None:
                raise NotFoundError(f"Company {company_id} not found")
            if values:
                await uow.companies.update(company_id, **values)
                await self._record_audit(
                    uow,
                    super_admin_id=super_admin_id,
                    action=PlatformAuditAction.COMPANY_UPDATED.value,
                    resource_type="company",
                    resource_id=company_id,
                    company_id=company_id,
                    summary=f"Updated company profile {company.name}",
                    details=values,
                )
                await uow.commit()
        return await self.get_company(company_id)

    async def set_company_active(
        self,
        company_id: UUID,
        *,
        is_active: bool,
        super_admin_id: UUID | None = None,
    ) -> Company:
        async with self._uow_factory() as uow:
            company = await uow.companies.get_by_id(company_id)
            if company is None:
                raise NotFoundError(f"Company {company_id} not found")
            updated = await uow.companies.update(company_id, is_active=is_active)
            await self._record_audit(
                uow,
                super_admin_id=super_admin_id,
                action=(
                    PlatformAuditAction.COMPANY_ACTIVATED.value
                    if is_active
                    else PlatformAuditAction.COMPANY_DEACTIVATED.value
                ),
                resource_type="company",
                resource_id=company_id,
                company_id=company_id,
                summary=f"{'Activated' if is_active else 'Deactivated'} company {company.name}",
            )
            await uow.commit()
            if updated is None:
                raise NotFoundError(f"Company {company_id} not found")
            return updated

    async def get_subscription(self, company_id: UUID) -> CompanySubscriptionResponse:
        async with self._uow_factory() as uow:
            company = await uow.companies.get_by_id(company_id)
            if company is None:
                raise NotFoundError(f"Company {company_id} not found")
            subscription = await uow.company_subscriptions.get_current_for_company(company_id)
            if subscription is None:
                raise NotFoundError("Subscription not found")
            return self._subscription_response(subscription)

    async def update_subscription(
        self,
        company_id: UUID,
        payload: CompanySubscriptionUpdate,
        *,
        super_admin_id: UUID | None = None,
    ) -> CompanySubscriptionResponse:
        values = payload.model_dump(exclude_unset=True)
        if not values:
            return await self.get_subscription(company_id)

        async with self._uow_factory() as uow:
            subscription = await uow.company_subscriptions.get_current_for_company(company_id)
            if subscription is None:
                raise NotFoundError("Subscription not found")

            prev_status = subscription.status
            prev_tier = subscription.tier
            update_values = dict(values)

            if "tier" in update_values:
                limits = tier_limits(update_values["tier"])
                update_values["employee_limit"] = limits["employees"]
                update_values["program_limit"] = limits["programs"]

            updated = await uow.company_subscriptions.update(subscription.id, **update_values)
            if updated is None:
                raise NotFoundError("Subscription not found")

            if "status" in update_values and update_values["status"] != prev_status:
                await self._record_subscription_event(
                    uow,
                    subscription=updated,
                    event_type=SubscriptionHistoryEventType.STATUS_CHANGED.value,
                    super_admin_id=super_admin_id,
                    previous_status=prev_status,
                    new_status=updated.status,
                )
            if "tier" in update_values and update_values["tier"] != prev_tier:
                await self._record_subscription_event(
                    uow,
                    subscription=updated,
                    event_type=SubscriptionHistoryEventType.TIER_CHANGED.value,
                    super_admin_id=super_admin_id,
                    previous_tier=prev_tier,
                    new_tier=updated.tier,
                )
            if "auto_renew" in update_values:
                await self._record_subscription_event(
                    uow,
                    subscription=updated,
                    event_type=SubscriptionHistoryEventType.AUTO_RENEW_CHANGED.value,
                    super_admin_id=super_admin_id,
                    note=f"auto_renew={updated.auto_renew}",
                )

            await self._record_audit(
                uow,
                super_admin_id=super_admin_id,
                action=PlatformAuditAction.SUBSCRIPTION_UPDATED.value,
                resource_type="subscription",
                resource_id=updated.id,
                company_id=company_id,
                summary=f"Updated subscription for company {company_id}",
                details=values,
            )
            await uow.commit()
            return self._subscription_response(updated)

    async def list_subscription_history(
        self,
        company_id: UUID,
        *,
        offset: int = 0,
        limit: int = 100,
    ) -> list[SubscriptionHistoryResponse]:
        async with self._uow_factory() as uow:
            company = await uow.companies.get_by_id(company_id)
            if company is None:
                raise NotFoundError(f"Company {company_id} not found")
            events = await uow.subscription_history.list_for_company(
                company_id,
                offset=offset,
                limit=limit,
            )
            return [SubscriptionHistoryResponse.model_validate(e) for e in events]

    async def list_subscriptions(
        self,
        company_id: UUID,
        *,
        offset: int = 0,
        limit: int = 100,
    ) -> list[CompanySubscriptionResponse]:
        async with self._uow_factory() as uow:
            subs = await uow.company_subscriptions.list_for_company(
                company_id,
                offset=offset,
                limit=limit,
            )
            return [self._subscription_response(s) for s in subs]

    async def get_company_limits(self, company_id: UUID) -> CompanyLimitsResponse:
        async with self._uow_factory() as uow:
            company = await uow.companies.get_by_id(company_id)
            if company is None:
                raise NotFoundError(f"Company {company_id} not found")
            subscription = await uow.company_subscriptions.get_current_for_company(company_id)
            usage = await self._usage_counts(uow, company_id)
            return await self._limits_response(uow, company_id, subscription, usage)

    async def list_company_users(
        self,
        company_id: UUID,
        *,
        offset: int = 0,
        limit: int = 100,
        role: str | None = None,
        status: str | None = None,
    ) -> list[PlatformUserResponse]:
        async with self._uow_factory() as uow:
            company = await uow.companies.get_by_id(company_id)
            if company is None:
                raise NotFoundError(f"Company {company_id} not found")
            stmt = (
                select(Employee)
                .where(Employee.company_id == company_id)
                .order_by(Employee.created_at.desc())
                .offset(offset)
                .limit(limit)
            )
            if role is not None:
                stmt = stmt.where(Employee.role == role)
            if status is not None:
                stmt = stmt.where(Employee.status == status)
            employees = list((await uow.session.scalars(stmt)).all())
            return [self._user_response(emp, company) for emp in employees]

    async def create_company_user(
        self,
        company_id: UUID,
        payload: CompanyUserCreate,
        *,
        super_admin_id: UUID | None = None,
    ) -> PlatformUserResponse:
        if payload.role not in _COMPANY_ROLES:
            raise ValidationError(f"Invalid role {payload.role!r}")

        async with self._uow_factory() as uow:
            company = await uow.companies.get_by_id(company_id)
            if company is None:
                raise NotFoundError(f"Company {company_id} not found")
            subscription = await uow.company_subscriptions.get_current_for_company(company_id)
            usage = await self._usage_counts(uow, company_id)
            if subscription and usage["employees_count"] >= subscription.employee_limit:
                raise ValidationError("Employee limit reached for this company")

            telegram_user_id = payload.telegram_user_id or (uuid4().int % 1_000_000_000 + 1000)
            try:
                employee = await uow.employees.create(
                    Employee(
                        company_id=company_id,
                        telegram_user_id=telegram_user_id,
                        full_name=payload.full_name,
                        email=payload.email.strip().lower(),
                        role=payload.role,
                        status=EmployeeStatus.INVITED.value,
                    ),
                )
                await self._record_audit(
                    uow,
                    super_admin_id=super_admin_id,
                    action=PlatformAuditAction.USER_CREATED.value,
                    resource_type="employee",
                    resource_id=employee.id,
                    company_id=company_id,
                    summary=f"Created user {employee.full_name}",
                    details={"role": employee.role, "email": employee.email},
                )
                await uow.commit()
            except IntegrityError as exc:
                await uow.rollback()
                raise ConflictError("Employee telegram_user_id already exists") from exc

        await self._invites.create_and_send_invite(
            employee=employee,
            invited_email=payload.email,
            company_name=company.name,
            super_admin_id=super_admin_id,
        )
        return self._user_response(employee, company)

    async def resend_invite(
        self,
        employee_id: UUID,
        *,
        super_admin_id: UUID | None = None,
    ) -> None:
        async with self._uow_factory() as uow:
            employee = await uow.employees.get_by_id(employee_id)
            if employee is None:
                raise NotFoundError(f"Employee {employee_id} not found")
            company = await uow.companies.get_by_id(employee.company_id)
            if company is None:
                raise NotFoundError("Company not found")
            if not employee.email:
                raise ValidationError("Employee has no email for invite")
            await self._record_audit(
                uow,
                super_admin_id=super_admin_id,
                action=PlatformAuditAction.USER_INVITED.value,
                resource_type="employee",
                resource_id=employee.id,
                company_id=employee.company_id,
                summary=f"Resent invite to {employee.email}",
            )
            await uow.commit()

        await self._invites.create_and_send_invite(
            employee=employee,
            invited_email=employee.email,
            company_name=company.name,
            super_admin_id=super_admin_id,
        )

    async def list_company_admins(
        self,
        *,
        offset: int = 0,
        limit: int = 100,
        company_id: UUID | None = None,
        role: str | None = None,
        status: str | None = None,
    ) -> list[PlatformUserResponse]:
        if role is not None and role not in _MANAGEMENT_ROLES:
            raise ValidationError(
                f"Invalid role filter {role!r}; expected one of {sorted(_MANAGEMENT_ROLES)}"
            )
        async with self._uow_factory() as uow:
            stmt = (
                select(Employee, Company.name, Company.slug)
                .join(Company, Company.id == Employee.company_id)
                .where(Employee.role.in_(sorted(_MANAGEMENT_ROLES)))
            )
            if company_id is not None:
                stmt = stmt.where(Employee.company_id == company_id)
            if role is not None:
                stmt = stmt.where(Employee.role == role)
            if status is not None:
                stmt = stmt.where(Employee.status == status)
            stmt = stmt.order_by(Employee.created_at.desc()).offset(offset).limit(limit)
            rows = (await uow.session.execute(stmt)).all()
            return [
                PlatformUserResponse(
                    id=emp.id,
                    company_id=emp.company_id,
                    company_name=cname,
                    company_slug=cslug,
                    full_name=emp.full_name,
                    email=emp.email,
                    role=emp.role,
                    status=emp.status,
                    telegram_user_id=emp.telegram_user_id,
                    telegram_username=emp.telegram_username,
                    last_login_at=emp.last_login_at,
                    created_at=emp.created_at,
                    updated_at=emp.updated_at,
                )
                for emp, cname, cslug in rows
            ]

    async def update_company_user(
        self,
        employee_id: UUID,
        *,
        role: str | None = None,
        status: str | None = None,
        super_admin_id: UUID | None = None,
    ) -> PlatformUserResponse:
        if role is not None and role not in _COMPANY_ROLES:
            raise ValidationError(
                f"Invalid role {role!r}; expected one of {sorted(_COMPANY_ROLES)}"
            )
        values: dict[str, Any] = {}
        if role is not None:
            values["role"] = role
        if status is not None:
            values["status"] = status
        if not values:
            raise ValidationError("No fields to update")

        async with self._uow_factory() as uow:
            employee = await uow.employees.get_by_id(employee_id)
            if employee is None:
                raise NotFoundError(f"Employee {employee_id} not found")
            updated = await uow.employees.update(employee_id, **values)
            if updated is None:
                raise NotFoundError(f"Employee {employee_id} not found")
            company = await uow.companies.get_by_id(updated.company_id)
            await self._record_audit(
                uow,
                super_admin_id=super_admin_id,
                action=PlatformAuditAction.USER_UPDATED.value,
                resource_type="employee",
                resource_id=employee_id,
                company_id=updated.company_id,
                summary=f"Updated user {updated.full_name}",
                details=values,
            )
            await uow.commit()
            return self._user_response(updated, company)

    async def block_company_user(
        self,
        employee_id: UUID,
        *,
        super_admin_id: UUID | None = None,
    ) -> PlatformUserResponse:
        result = await self.update_company_user(
            employee_id,
            status=EmployeeStatus.ARCHIVED.value,
            super_admin_id=super_admin_id,
        )
        async with self._uow_factory() as uow:
            await self._record_audit(
                uow,
                super_admin_id=super_admin_id,
                action=PlatformAuditAction.USER_BLOCKED.value,
                resource_type="employee",
                resource_id=employee_id,
                company_id=result.company_id,
                summary=f"Blocked user {result.full_name}",
            )
            await uow.commit()
        return result

    async def list_audit_logs(
        self,
        *,
        offset: int = 0,
        limit: int = 100,
        company_id: UUID | None = None,
    ) -> list[PlatformAuditLogResponse]:
        async with self._uow_factory() as uow:
            logs = await uow.platform_audit_logs.list_recent(
                offset=offset,
                limit=limit,
                company_id=company_id,
            )
            return [PlatformAuditLogResponse.model_validate(log) for log in logs]

    async def preview_invite(self, token: str) -> InvitePreviewResponse:
        data = await self._invites.get_invite_preview(token)
        return InvitePreviewResponse.model_validate(data)

    async def accept_invite(self, payload: InviteAcceptRequest) -> Employee:
        return await self._invites.accept_invite(
            token=payload.token,
            password=payload.password,
        )

    def get_settings(self) -> PlatformSettingsResponse:
        return _PLATFORM_SETTINGS.model_copy()

    def update_settings(
        self,
        payload: PlatformSettingsUpdate,
        *,
        super_admin_id: UUID | None = None,
    ) -> PlatformSettingsResponse:
        global _PLATFORM_SETTINGS
        data = _PLATFORM_SETTINGS.model_dump()
        data.update(payload.model_dump(exclude_unset=True))
        _PLATFORM_SETTINGS = PlatformSettingsResponse(**data)
        return _PLATFORM_SETTINGS.model_copy()

    @staticmethod
    def _subscription_response(sub: CompanySubscription) -> CompanySubscriptionResponse:
        return CompanySubscriptionResponse(
            id=sub.id,
            company_id=sub.company_id,
            tier=sub.tier,
            status=sub.status,
            payment_status=sub.payment_status,
            started_at=sub.started_at,
            ends_at=sub.ends_at,
            auto_renew=sub.auto_renew,
            employee_limit=sub.employee_limit,
            program_limit=sub.program_limit,
            is_current=sub.is_current,
            created_at=sub.created_at,
            updated_at=sub.updated_at,
        )

    async def _limits_response(
        self,
        uow: UnitOfWork,
        company_id: UUID,
        subscription: CompanySubscription | None,
        usage: dict[str, int],
    ) -> CompanyLimitsResponse:
        limits = tier_limits(subscription.tier if subscription else SubscriptionTier.STARTER.value)
        return CompanyLimitsResponse(
            company_id=company_id,
            employee_limit=subscription.employee_limit if subscription else limits["employees"],
            employees_used=usage["employees_count"],
            program_limit=subscription.program_limit if subscription else limits["programs"],
            programs_used=usage["programs_count"],
        )

    @staticmethod
    def _user_response(employee: Employee, company: Company | None) -> PlatformUserResponse:
        return PlatformUserResponse(
            id=employee.id,
            company_id=employee.company_id,
            company_name=company.name if company else None,
            company_slug=company.slug if company else None,
            full_name=employee.full_name,
            email=employee.email,
            role=employee.role,
            status=employee.status,
            telegram_user_id=employee.telegram_user_id,
            telegram_username=employee.telegram_username,
            last_login_at=employee.last_login_at,
            created_at=employee.created_at,
            updated_at=employee.updated_at,
        )

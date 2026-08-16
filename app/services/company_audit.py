"""Tenant audit writes that reuse the platform-audit pattern without mixing RLS."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any
from uuid import UUID

from app.core.exceptions import NotFoundError, ValidationError
from app.db.enums import CompanyAuditAction
from app.db.models.company_audit_log import CompanyAuditLog
from app.db.uow import UnitOfWork
from app.services.tenancy import ensure_same_company

_SENSITIVE_KEY_FRAGMENTS = (
    "password",
    "token",
    "secret",
    "hash",
    "invite_url",
    "credential",
)

_ALLOWED_ACTIONS = {item.value for item in CompanyAuditAction}


def _is_sensitive_key(key: str) -> bool:
    lowered = key.lower()
    return any(fragment in lowered for fragment in _SENSITIVE_KEY_FRAGMENTS)


def sanitize_audit_details(details: dict[str, Any] | None) -> dict[str, Any]:
    """Drop credentials and invite secrets from stored audit details."""
    if not details:
        return {}
    cleaned: dict[str, Any] = {}
    for key, value in details.items():
        if not isinstance(key, str) or _is_sensitive_key(key):
            continue
        cleaned[key] = value
    return cleaned


async def record_company_audit(
    uow: UnitOfWork,
    *,
    company_id: UUID,
    action: str,
    resource_type: str,
    summary: str,
    actor_employee_id: UUID | None = None,
    resource_id: UUID | None = None,
    details: dict[str, Any] | None = None,
) -> None:
    actor_name: str | None = None
    if actor_employee_id is not None:
        actor = await uow.employees.get_by_id(actor_employee_id)
        if actor is not None:
            actor_name = actor.full_name
    await uow.company_audit_logs.create(
        CompanyAuditLog(
            company_id=company_id,
            actor_employee_id=actor_employee_id,
            actor_name=actor_name,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            summary=summary,
            details=sanitize_audit_details(details),
        ),
    )


class CompanyAuditService:
    """List tenant audit events for HR/Admin."""

    def __init__(self, uow_factory: Callable[[], UnitOfWork] | None = None) -> None:
        self._uow_factory = uow_factory or UnitOfWork

    async def list_events(
        self,
        company_id: UUID,
        *,
        actor_company_id: UUID,
        action: str | None = None,
        resource_type: str | None = None,
        offset: int = 0,
        limit: int = 100,
    ) -> list[CompanyAuditLog]:
        ensure_same_company(
            resource_company_id=company_id,
            actor_company_id=actor_company_id,
            not_found_message=f"Company {company_id} not found",
        )
        if action is not None and action not in _ALLOWED_ACTIONS:
            raise ValidationError(
                f"Invalid audit action {action!r}; allowed: {sorted(_ALLOWED_ACTIONS)}"
            )
        async with self._uow_factory() as uow:
            await uow.enter_tenant(company_id)
            company = await uow.companies.get_by_id(company_id)
            if company is None:
                raise NotFoundError(f"Company {company_id} not found")
            return await uow.company_audit_logs.list_by_company_id(
                company_id,
                action=action,
                resource_type=resource_type,
                offset=offset,
                limit=limit,
            )

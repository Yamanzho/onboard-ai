"""Tenant audit log: event creation, RBAC, isolation, no secrets."""

from __future__ import annotations

from uuid import uuid4

import pytest
from httpx import AsyncClient

from app.db.enums import CompanyAuditAction
from app.db.models.company import Company
from app.db.models.employee import Employee
from app.services.company_audit import sanitize_audit_details
from tests.conftest import auth_header


def test_sanitize_audit_details_drops_secrets() -> None:
    cleaned = sanitize_audit_details(
        {
            "role": "employee",
            "password": "secret",
            "invite_token": "abc",
            "token_hash": "deadbeef",
            "invite_url": "https://example/invite#tok",
            "delivery": "email",
        }
    )
    assert cleaned == {"role": "employee", "delivery": "email"}
    assert "password" not in cleaned
    assert "token" not in str(cleaned).lower()


@pytest.mark.asyncio
async def test_hr_audit_events_are_tenant_scoped(
    api_client: AsyncClient,
    company_a: Company,
    company_b: Company,
    hr_a: Employee,
    hr_b: Employee,
    employee_a: Employee,
) -> None:
    marker = uuid4().hex[:8]
    created = await api_client.post(
        "/api/v1/employees",
        headers=auth_header(hr_a),
        json={
            "company_id": str(company_a.id),
            "full_name": f"Audit Emp {marker}",
            "email": f"audit-{marker}@example.com",
            "role": "employee",
            "status": "invited",
        },
    )
    assert created.status_code == 201, created.text
    assert "invite_url" in created.json()

    listed = await api_client.get(
        f"/api/v1/audit-logs?company_id={company_a.id}",
        headers=auth_header(hr_a),
    )
    assert listed.status_code == 200, listed.text
    items = listed.json()["items"]
    actions = {row["action"] for row in items}
    assert CompanyAuditAction.EMPLOYEE_CREATED.value in actions
    assert CompanyAuditAction.INVITE_CREATED.value in actions
    blob = listed.text.lower()
    assert "password" not in blob
    assert "token" not in blob
    assert created.json().get("invite_url") not in listed.text

    employee_denied = await api_client.get(
        f"/api/v1/audit-logs?company_id={company_a.id}",
        headers=auth_header(employee_a),
    )
    assert employee_denied.status_code == 403

    cross_company = await api_client.get(
        f"/api/v1/audit-logs?company_id={company_a.id}",
        headers=auth_header(hr_b),
    )
    assert cross_company.status_code == 404

    other_list = await api_client.get(
        f"/api/v1/audit-logs?company_id={company_b.id}",
        headers=auth_header(hr_b),
    )
    assert other_list.status_code == 200
    other_summaries = " ".join(row["summary"] for row in other_list.json()["items"])
    assert marker not in other_summaries

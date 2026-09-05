"""API permission checks via capabilities for Admin / HR / Employee."""

from __future__ import annotations

from uuid import uuid4

import pytest
from httpx import AsyncClient

from tests.conftest import auth_header


@pytest.mark.asyncio
async def test_employee_cannot_manage_assignments_or_courses(
    api_client: AsyncClient,
    company_a,
    employee_a,
    hr_a,
) -> None:
    emp = auth_header(employee_a)
    hr = auth_header(hr_a)

    listed = await api_client.get(
        f"/api/v1/assignments?company_id={company_a.id}",
        headers=emp,
    )
    assert listed.status_code == 403

    created = await api_client.post(
        "/api/v1/assignments",
        headers=emp,
        json={"employee_id": str(employee_a.id), "program_id": str(uuid4())},
    )
    assert created.status_code in {403, 404, 422}

    programs = await api_client.get(
        f"/api/v1/programs?company_id={company_a.id}",
        headers=emp,
    )
    assert programs.status_code == 403

    program = await api_client.post(
        "/api/v1/programs",
        headers=emp,
        json={"company_id": str(company_a.id), "title": "Nope"},
    )
    assert program.status_code == 403

    # HR still allowed to list programs (capability mapping).
    ok = await api_client.get(
        f"/api/v1/programs?company_id={company_a.id}",
        headers=hr,
    )
    assert ok.status_code == 200


@pytest.mark.asyncio
async def test_employee_cannot_view_company_progress_or_analytics(
    api_client: AsyncClient,
    company_a,
    employee_a,
) -> None:
    emp = auth_header(employee_a)
    analytics = await api_client.get(
        f"/api/v1/analytics/assignments?company_id={company_a.id}",
        headers=emp,
    )
    assert analytics.status_code == 403
    onboarding = await api_client.get(
        f"/api/v1/analytics/onboarding?company_id={company_a.id}",
        headers=emp,
    )
    assert onboarding.status_code == 403
    employees = await api_client.get(
        f"/api/v1/employees?company_id={company_a.id}",
        headers=emp,
    )
    assert employees.status_code == 403


@pytest.mark.asyncio
async def test_hr_and_admin_can_manage_operational_surfaces(
    api_client: AsyncClient,
    company_a,
    hr_a,
    admin_a,
) -> None:
    for actor in (hr_a, admin_a):
        headers = auth_header(actor)
        employees = await api_client.get(
            f"/api/v1/employees?company_id={company_a.id}",
            headers=headers,
        )
        assert employees.status_code == 200, employees.text
        assignments = await api_client.get(
            f"/api/v1/assignments?company_id={company_a.id}",
            headers=headers,
        )
        assert assignments.status_code == 200, assignments.text
        analytics = await api_client.get(
            f"/api/v1/analytics/assignments?company_id={company_a.id}",
            headers=headers,
        )
        assert analytics.status_code == 200, analytics.text


@pytest.mark.asyncio
async def test_hr_cannot_change_company_settings(
    api_client: AsyncClient,
    company_a,
    hr_a,
    admin_a,
) -> None:
    denied = await api_client.patch(
        f"/api/v1/companies/{company_a.id}",
        headers=auth_header(hr_a),
        json={"timezone": "Europe/Berlin"},
    )
    assert denied.status_code == 403
    allowed = await api_client.patch(
        f"/api/v1/companies/{company_a.id}",
        headers=auth_header(admin_a),
        json={"timezone": "Europe/Berlin"},
    )
    assert allowed.status_code == 200, allowed.text


@pytest.mark.asyncio
async def test_me_returns_server_resolved_capabilities(
    api_client: AsyncClient,
    admin_a,
    hr_a,
    employee_a,
) -> None:
    admin_me = await api_client.get("/api/v1/auth/me", headers=auth_header(admin_a))
    assert admin_me.status_code == 200
    assert "company.settings.manage" in admin_me.json()["capabilities"]
    hr_me = await api_client.get("/api/v1/auth/me", headers=auth_header(hr_a))
    assert hr_me.status_code == 200
    assert "assignments.manage" in hr_me.json()["capabilities"]
    assert "company.settings.manage" not in hr_me.json()["capabilities"]
    emp_me = await api_client.get("/api/v1/auth/me", headers=auth_header(employee_a))
    assert emp_me.status_code == 200
    assert emp_me.json()["capabilities"] == [
        "assignments.view_own",
        "knowledge.view",
        "progress.view_own",
    ]

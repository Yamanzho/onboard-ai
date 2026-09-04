"""Phase 9B: department CRUD, ACL, tenant isolation, unique slugs."""

from __future__ import annotations

from uuid import uuid4

from httpx import AsyncClient

from app.db.models.company import Company
from app.db.models.employee import Employee
from tests.conftest import auth_header


async def _create_department(
    client: AsyncClient,
    actor: Employee,
    company_id,
    *,
    name: str = "HR",
    slug: str | None = "hr",
) -> dict:
    res = await client.post(
        "/api/v1/departments",
        headers=auth_header(actor),
        json={
            "company_id": str(company_id),
            "name": name,
            "slug": slug,
        },
    )
    assert res.status_code == 201, res.text
    return res.json()


async def test_admin_can_create_department(
    api_client: AsyncClient,
    company_a: Company,
    admin_a: Employee,
) -> None:
    body = await _create_department(api_client, admin_a, company_a.id, name="IT", slug="it")
    assert body["name"] == "IT"
    assert body["slug"] == "it"
    assert body["company_id"] == str(company_a.id)
    assert body["is_active"] is True


async def test_hr_can_create_department(
    api_client: AsyncClient,
    company_a: Company,
    hr_a: Employee,
) -> None:
    body = await _create_department(api_client, hr_a, company_a.id, slug="people")
    assert body["slug"] == "people"


async def test_employee_cannot_create_department(
    api_client: AsyncClient,
    company_a: Company,
    employee_a: Employee,
) -> None:
    res = await api_client.post(
        "/api/v1/departments",
        headers=auth_header(employee_a),
        json={"company_id": str(company_a.id), "name": "HR", "slug": "hr"},
    )
    assert res.status_code == 403, res.text


async def test_list_departments_is_tenant_scoped(
    api_client: AsyncClient,
    company_a: Company,
    company_b: Company,
    admin_a: Employee,
    admin_b: Employee,
) -> None:
    await _create_department(api_client, admin_a, company_a.id, slug="hr-a")
    await _create_department(api_client, admin_b, company_b.id, slug="hr-b")

    listed = await api_client.get(
        f"/api/v1/departments?company_id={company_a.id}",
        headers=auth_header(admin_a),
    )
    assert listed.status_code == 200, listed.text
    slugs = {row["slug"] for row in listed.json()}
    assert "hr-a" in slugs
    assert "hr-b" not in slugs

    foreign_list = await api_client.get(
        f"/api/v1/departments?company_id={company_b.id}",
        headers=auth_header(admin_a),
    )
    assert foreign_list.status_code == 404, foreign_list.text


async def test_update_and_deactivate_department(
    api_client: AsyncClient,
    company_a: Company,
    admin_a: Employee,
) -> None:
    created = await _create_department(api_client, admin_a, company_a.id, slug="ops")
    patched = await api_client.patch(
        f"/api/v1/departments/{created['id']}",
        headers=auth_header(admin_a),
        json={"name": "Operations", "is_active": False},
    )
    assert patched.status_code == 200, patched.text
    assert patched.json()["name"] == "Operations"
    assert patched.json()["is_active"] is False


async def test_department_slug_unique_within_tenant(
    api_client: AsyncClient,
    company_a: Company,
    admin_a: Employee,
) -> None:
    await _create_department(api_client, admin_a, company_a.id, slug="finance")
    dup = await api_client.post(
        "/api/v1/departments",
        headers=auth_header(admin_a),
        json={"company_id": str(company_a.id), "name": "Finance 2", "slug": "finance"},
    )
    assert dup.status_code == 409, dup.text


async def test_same_department_slug_allowed_in_another_tenant(
    api_client: AsyncClient,
    company_a: Company,
    company_b: Company,
    admin_a: Employee,
    admin_b: Employee,
) -> None:
    await _create_department(api_client, admin_a, company_a.id, slug="shared")
    other = await _create_department(api_client, admin_b, company_b.id, slug="shared")
    assert other["slug"] == "shared"
    assert other["company_id"] == str(company_b.id)


async def test_cross_tenant_department_get_is_404(
    api_client: AsyncClient,
    company_b: Company,
    admin_a: Employee,
    admin_b: Employee,
) -> None:
    created = await _create_department(api_client, admin_b, company_b.id, slug="secret")
    res = await api_client.get(
        f"/api/v1/departments/{created['id']}",
        headers=auth_header(admin_a),
    )
    assert res.status_code == 404, res.text
    missing = await api_client.get(
        f"/api/v1/departments/{uuid4()}",
        headers=auth_header(admin_a),
    )
    assert missing.status_code == 404, missing.text

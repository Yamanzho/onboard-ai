"""Phase 9B: question topics and topic responsibilities."""

from __future__ import annotations

from uuid import uuid4

from httpx import AsyncClient

from app.core.security import hash_password
from app.db.enums import EmployeeRole, EmployeeStatus
from app.db.models.company import Company
from app.db.models.employee import Employee
from tests.conftest import _uow_factory, auth_header


async def _create_department(
    client: AsyncClient,
    actor: Employee,
    company_id,
    *,
    slug: str,
    name: str = "HR",
    is_active: bool = True,
) -> dict:
    res = await client.post(
        "/api/v1/departments",
        headers=auth_header(actor),
        json={
            "company_id": str(company_id),
            "name": name,
            "slug": slug,
            "is_active": is_active,
        },
    )
    assert res.status_code == 201, res.text
    return res.json()


async def _create_topic(
    client: AsyncClient,
    actor: Employee,
    company_id,
    *,
    name: str = "Vacation",
    slug: str = "vacation",
    department_id: str | None = None,
    employee_id: str | None = None,
) -> dict:
    payload: dict = {
        "company_id": str(company_id),
        "name": name,
        "slug": slug,
    }
    if department_id is not None:
        payload["department_id"] = department_id
    if employee_id is not None:
        payload["employee_id"] = employee_id
    res = await client.post(
        "/api/v1/topics",
        headers=auth_header(actor),
        json=payload,
    )
    assert res.status_code == 201, res.text
    return res.json()


async def _create_peer(
    company_id,
    *,
    status: str = EmployeeStatus.ACTIVE.value,
) -> Employee:
    async with _uow_factory() as uow:
        await uow.enter_platform()
        employee = await uow.employees.create(
            Employee(
                company_id=company_id,
                telegram_user_id=uuid4().int % 1_000_000_000 + 7000,
                full_name="Topic Owner",
                email=f"topic-{uuid4().hex[:8]}@example.com",
                role=EmployeeRole.EMPLOYEE.value,
                status=status,
                password_hash=hash_password("TopicOwner1!")
                if status == EmployeeStatus.ACTIVE.value
                else None,
            ),
        )
        await uow.commit()
        return employee


async def test_admin_and_hr_can_create_topic(
    api_client: AsyncClient,
    company_a: Company,
    admin_a: Employee,
    hr_a: Employee,
) -> None:
    admin_topic = await _create_topic(api_client, admin_a, company_a.id, slug="vacation")
    assert admin_topic["name"] == "Vacation"
    assert admin_topic["responsibility"] is None
    hr_topic = await _create_topic(api_client, hr_a, company_a.id, slug="sick-leave")
    assert hr_topic["slug"] == "sick-leave"


async def test_employee_cannot_create_topic(
    api_client: AsyncClient,
    company_a: Company,
    employee_a: Employee,
) -> None:
    res = await api_client.post(
        "/api/v1/topics",
        headers=auth_header(employee_a),
        json={"company_id": str(company_a.id), "name": "Vacation", "slug": "vacation"},
    )
    assert res.status_code == 403, res.text


async def test_update_and_deactivate_topic(
    api_client: AsyncClient,
    company_a: Company,
    admin_a: Employee,
) -> None:
    created = await _create_topic(api_client, admin_a, company_a.id)
    patched = await api_client.patch(
        f"/api/v1/topics/{created['id']}",
        headers=auth_header(admin_a),
        json={"name": "Paid vacation", "is_active": False},
    )
    assert patched.status_code == 200, patched.text
    assert patched.json()["name"] == "Paid vacation"
    assert patched.json()["is_active"] is False


async def test_topic_slug_unique_per_tenant_and_reusable_elsewhere(
    api_client: AsyncClient,
    company_a: Company,
    company_b: Company,
    admin_a: Employee,
    admin_b: Employee,
) -> None:
    await _create_topic(api_client, admin_a, company_a.id, slug="salary")
    dup = await api_client.post(
        "/api/v1/topics",
        headers=auth_header(admin_a),
        json={"company_id": str(company_a.id), "name": "Salary 2", "slug": "salary"},
    )
    assert dup.status_code == 409, dup.text
    other = await _create_topic(api_client, admin_b, company_b.id, slug="salary")
    assert other["company_id"] == str(company_b.id)


async def test_topics_are_tenant_isolated(
    api_client: AsyncClient,
    company_a: Company,
    company_b: Company,
    admin_a: Employee,
    admin_b: Employee,
) -> None:
    local = await _create_topic(api_client, admin_a, company_a.id, slug="local")
    foreign = await _create_topic(api_client, admin_b, company_b.id, slug="foreign")
    listed = await api_client.get(
        f"/api/v1/topics?company_id={company_a.id}",
        headers=auth_header(admin_a),
    )
    assert listed.status_code == 200, listed.text
    ids = {row["id"] for row in listed.json()}
    assert local["id"] in ids
    assert foreign["id"] not in ids
    hidden = await api_client.get(
        f"/api/v1/topics/{foreign['id']}",
        headers=auth_header(admin_a),
    )
    assert hidden.status_code == 404, hidden.text


async def test_responsibility_department_only(
    api_client: AsyncClient,
    company_a: Company,
    admin_a: Employee,
) -> None:
    dept = await _create_department(api_client, admin_a, company_a.id, slug="hr")
    topic = await _create_topic(
        api_client,
        admin_a,
        company_a.id,
        department_id=dept["id"],
    )
    mapping = topic["responsibility"]
    assert mapping is not None
    assert mapping["department_id"] == dept["id"]
    assert mapping["employee_id"] is None
    assert mapping["department"]["name"] == "HR"


async def test_responsibility_employee_only(
    api_client: AsyncClient,
    company_a: Company,
    admin_a: Employee,
    employee_a: Employee,
) -> None:
    topic = await _create_topic(api_client, admin_a, company_a.id, slug="manager-q")
    res = await api_client.put(
        f"/api/v1/topics/{topic['id']}/responsibility",
        headers=auth_header(admin_a),
        json={"employee_id": str(employee_a.id)},
    )
    assert res.status_code == 200, res.text
    mapping = res.json()["responsibility"]
    assert mapping["employee_id"] == str(employee_a.id)
    assert mapping["department_id"] is None
    assert mapping["employee"]["full_name"] == employee_a.full_name


async def test_responsibility_department_and_employee(
    api_client: AsyncClient,
    company_a: Company,
    admin_a: Employee,
    employee_a: Employee,
) -> None:
    dept = await _create_department(api_client, admin_a, company_a.id, slug="it")
    topic = await _create_topic(
        api_client,
        admin_a,
        company_a.id,
        slug="it-access",
        department_id=dept["id"],
        employee_id=str(employee_a.id),
    )
    mapping = topic["responsibility"]
    assert mapping["department_id"] == dept["id"]
    assert mapping["employee_id"] == str(employee_a.id)


async def test_responsibility_rejects_neither_target(
    api_client: AsyncClient,
    company_a: Company,
    admin_a: Employee,
) -> None:
    topic = await _create_topic(api_client, admin_a, company_a.id, slug="empty")
    res = await api_client.put(
        f"/api/v1/topics/{topic['id']}/responsibility",
        headers=auth_header(admin_a),
        json={"department_id": None, "employee_id": None},
    )
    assert res.status_code == 422, res.text


async def test_responsibility_rejects_cross_tenant_ids(
    api_client: AsyncClient,
    company_a: Company,
    company_b: Company,
    admin_a: Employee,
    admin_b: Employee,
    employee_b: Employee,
) -> None:
    foreign_dept = await _create_department(api_client, admin_b, company_b.id, slug="hr-b")
    topic = await _create_topic(api_client, admin_a, company_a.id, slug="cross")
    dept_res = await api_client.put(
        f"/api/v1/topics/{topic['id']}/responsibility",
        headers=auth_header(admin_a),
        json={"department_id": foreign_dept["id"]},
    )
    assert dept_res.status_code == 404, dept_res.text
    emp_res = await api_client.put(
        f"/api/v1/topics/{topic['id']}/responsibility",
        headers=auth_header(admin_a),
        json={"employee_id": str(employee_b.id)},
    )
    assert emp_res.status_code == 404, emp_res.text


async def test_responsibility_rejects_archived_employee_and_inactive_department(
    api_client: AsyncClient,
    company_a: Company,
    admin_a: Employee,
) -> None:
    inactive = await _create_department(
        api_client,
        admin_a,
        company_a.id,
        slug="legacy",
        is_active=True,
    )
    await api_client.patch(
        f"/api/v1/departments/{inactive['id']}",
        headers=auth_header(admin_a),
        json={"is_active": False},
    )
    archived = await _create_peer(company_a.id, status=EmployeeStatus.ARCHIVED.value)
    topic = await _create_topic(api_client, admin_a, company_a.id, slug="blocked")
    dept_res = await api_client.put(
        f"/api/v1/topics/{topic['id']}/responsibility",
        headers=auth_header(admin_a),
        json={"department_id": inactive["id"]},
    )
    assert dept_res.status_code == 400, dept_res.text
    emp_res = await api_client.put(
        f"/api/v1/topics/{topic['id']}/responsibility",
        headers=auth_header(admin_a),
        json={"employee_id": str(archived.id)},
    )
    assert emp_res.status_code == 400, emp_res.text

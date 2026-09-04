"""Phase 9B: employee department, manager, job title, and cycle rules."""

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
) -> dict:
    res = await client.post(
        "/api/v1/departments",
        headers=auth_header(actor),
        json={"company_id": str(company_id), "name": slug.upper(), "slug": slug},
    )
    assert res.status_code == 201, res.text
    return res.json()


async def _create_employee(
    company_id,
    *,
    full_name: str = "Org User",
    status: str = EmployeeStatus.ACTIVE.value,
) -> Employee:
    async with _uow_factory() as uow:
        await uow.enter_platform()
        employee = await uow.employees.create(
            Employee(
                company_id=company_id,
                telegram_user_id=uuid4().int % 1_000_000_000 + 8000,
                full_name=full_name,
                email=f"org-{uuid4().hex[:8]}@example.com",
                role=EmployeeRole.EMPLOYEE.value,
                status=status,
                password_hash=hash_password("OrgUserPass1!")
                if status == EmployeeStatus.ACTIVE.value
                else None,
            ),
        )
        await uow.commit()
        return employee


async def test_assign_department_job_title_and_manager(
    api_client: AsyncClient,
    company_a: Company,
    admin_a: Employee,
    employee_a: Employee,
) -> None:
    dept = await _create_department(api_client, admin_a, company_a.id, slug="hr")
    manager = await _create_employee(company_a.id, full_name="Aigerim")
    res = await api_client.patch(
        f"/api/v1/employees/{employee_a.id}",
        headers=auth_header(admin_a),
        json={
            "department_id": dept["id"],
            "manager_id": str(manager.id),
            "job_title": "People Partner",
        },
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["department_id"] == dept["id"]
    assert body["manager_id"] == str(manager.id)
    assert body["job_title"] == "People Partner"
    assert body["department"]["name"] == "HR"
    assert body["manager"]["full_name"] == "Aigerim"


async def test_hr_can_assign_org_fields(
    api_client: AsyncClient,
    company_a: Company,
    hr_a: Employee,
    employee_a: Employee,
) -> None:
    res = await api_client.patch(
        f"/api/v1/employees/{employee_a.id}",
        headers=auth_header(hr_a),
        json={"job_title": "Analyst"},
    )
    assert res.status_code == 200, res.text
    assert res.json()["job_title"] == "Analyst"


async def test_nullable_org_fields_remain_valid(
    api_client: AsyncClient,
    company_a: Company,
    admin_a: Employee,
    employee_a: Employee,
) -> None:
    detail = await api_client.get(
        f"/api/v1/employees/{employee_a.id}",
        headers=auth_header(admin_a),
    )
    assert detail.status_code == 200, detail.text
    body = detail.json()
    assert body["department_id"] is None
    assert body["manager_id"] is None
    assert body["job_title"] is None

    cleared = await api_client.patch(
        f"/api/v1/employees/{employee_a.id}",
        headers=auth_header(admin_a),
        json={"department_id": None, "manager_id": None, "job_title": None},
    )
    assert cleared.status_code == 200, cleared.text
    assert cleared.json()["department_id"] is None


async def test_reject_self_manager(
    api_client: AsyncClient,
    admin_a: Employee,
    employee_a: Employee,
) -> None:
    res = await api_client.patch(
        f"/api/v1/employees/{employee_a.id}",
        headers=auth_header(admin_a),
        json={"manager_id": str(employee_a.id)},
    )
    assert res.status_code == 400, res.text


async def test_reject_two_node_manager_cycle(
    api_client: AsyncClient,
    company_a: Company,
    admin_a: Employee,
) -> None:
    a = await _create_employee(company_a.id, full_name="A")
    b = await _create_employee(company_a.id, full_name="B")
    first = await api_client.patch(
        f"/api/v1/employees/{a.id}",
        headers=auth_header(admin_a),
        json={"manager_id": str(b.id)},
    )
    assert first.status_code == 200, first.text
    cycle = await api_client.patch(
        f"/api/v1/employees/{b.id}",
        headers=auth_header(admin_a),
        json={"manager_id": str(a.id)},
    )
    assert cycle.status_code == 400, cycle.text


async def test_reject_longer_manager_cycle(
    api_client: AsyncClient,
    company_a: Company,
    admin_a: Employee,
) -> None:
    a = await _create_employee(company_a.id, full_name="A")
    b = await _create_employee(company_a.id, full_name="B")
    c = await _create_employee(company_a.id, full_name="C")
    for employee_id, manager_id in ((a.id, b.id), (b.id, c.id)):
        res = await api_client.patch(
            f"/api/v1/employees/{employee_id}",
            headers=auth_header(admin_a),
            json={"manager_id": str(manager_id)},
        )
        assert res.status_code == 200, res.text
    cycle = await api_client.patch(
        f"/api/v1/employees/{c.id}",
        headers=auth_header(admin_a),
        json={"manager_id": str(a.id)},
    )
    assert cycle.status_code == 400, cycle.text


async def test_reject_archived_manager(
    api_client: AsyncClient,
    company_a: Company,
    admin_a: Employee,
    employee_a: Employee,
) -> None:
    archived = await _create_employee(
        company_a.id,
        full_name="Archived Boss",
        status=EmployeeStatus.ARCHIVED.value,
    )
    res = await api_client.patch(
        f"/api/v1/employees/{employee_a.id}",
        headers=auth_header(admin_a),
        json={"manager_id": str(archived.id)},
    )
    assert res.status_code == 400, res.text


async def test_cross_tenant_department_and_manager_rejected(
    api_client: AsyncClient,
    company_a: Company,
    company_b: Company,
    admin_a: Employee,
    admin_b: Employee,
    employee_a: Employee,
    employee_b: Employee,
) -> None:
    foreign_dept = await _create_department(api_client, admin_b, company_b.id, slug="it-b")
    dept_res = await api_client.patch(
        f"/api/v1/employees/{employee_a.id}",
        headers=auth_header(admin_a),
        json={"department_id": foreign_dept["id"]},
    )
    assert dept_res.status_code == 404, dept_res.text
    mgr_res = await api_client.patch(
        f"/api/v1/employees/{employee_a.id}",
        headers=auth_header(admin_a),
        json={"manager_id": str(employee_b.id)},
    )
    assert mgr_res.status_code == 404, mgr_res.text


async def test_list_employees_can_filter_by_department(
    api_client: AsyncClient,
    company_a: Company,
    admin_a: Employee,
    employee_a: Employee,
) -> None:
    dept = await _create_department(api_client, admin_a, company_a.id, slug="sales")
    assigned = await api_client.patch(
        f"/api/v1/employees/{employee_a.id}",
        headers=auth_header(admin_a),
        json={"department_id": dept["id"]},
    )
    assert assigned.status_code == 200, assigned.text
    listed = await api_client.get(
        f"/api/v1/employees?company_id={company_a.id}&department_id={dept['id']}",
        headers=auth_header(admin_a),
    )
    assert listed.status_code == 200, listed.text
    ids = {row["id"] for row in listed.json()}
    assert str(employee_a.id) in ids
    assert all(row["department_id"] == dept["id"] for row in listed.json())

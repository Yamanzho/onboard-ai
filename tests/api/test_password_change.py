"""Sprint 1.3: password change policy and confirm_password."""

from __future__ import annotations

from uuid import uuid4

import pytest
from httpx import AsyncClient

from app.core.security import hash_password, verify_password
from app.db.enums import EmployeeRole, EmployeeStatus
from app.db.models.employee import Employee
from tests.conftest import auth_header, _uow_factory

_PASSWORD = "ChangePass1!"
_NEW = "ChangePass2!"


async def _active(company_id) -> Employee:
    async with _uow_factory() as uow:
        await uow.enter_platform()
        employee = await uow.employees.create(
            Employee(
                company_id=company_id,
                telegram_user_id=uuid4().int % 1_000_000_000 + 7000,
                full_name="Pwd Change User",
                email=f"pwd-{uuid4().hex[:8]}@example.com",
                role=EmployeeRole.EMPLOYEE.value,
                status=EmployeeStatus.ACTIVE.value,
                password_hash=hash_password(_PASSWORD),
            ),
        )
        await uow.commit()
        return employee


async def test_password_change_rejects_mismatch_confirm(
    api_client: AsyncClient,
    company_a,
) -> None:
    employee = await _active(company_a.id)
    res = await api_client.post(
        "/api/v1/auth/password",
        headers=auth_header(employee),
        json={
            "current_password": _PASSWORD,
            "new_password": _NEW,
            "confirm_password": "Different1!",
        },
    )
    assert res.status_code == 422


async def test_password_change_rejects_short_password(
    api_client: AsyncClient,
    company_a,
) -> None:
    employee = await _active(company_a.id)
    res = await api_client.post(
        "/api/v1/auth/password",
        headers=auth_header(employee),
        json={
            "current_password": _PASSWORD,
            "new_password": "short",
            "confirm_password": "short",
        },
    )
    assert res.status_code == 422


async def test_password_change_rejects_same_as_current(
    api_client: AsyncClient,
    company_a,
) -> None:
    employee = await _active(company_a.id)
    res = await api_client.post(
        "/api/v1/auth/password",
        headers=auth_header(employee),
        json={
            "current_password": _PASSWORD,
            "new_password": _PASSWORD,
            "confirm_password": _PASSWORD,
        },
    )
    assert res.status_code == 400
    assert "different" in res.json()["detail"].lower()


async def test_password_change_success_never_returns_secrets(
    api_client: AsyncClient,
    company_a,
) -> None:
    employee = await _active(company_a.id)
    res = await api_client.post(
        "/api/v1/auth/password",
        headers=auth_header(employee),
        json={
            "current_password": _PASSWORD,
            "new_password": _NEW,
            "confirm_password": _NEW,
        },
    )
    assert res.status_code == 204
    assert res.content in (b"", b"null")

    me = await api_client.get("/api/v1/auth/me", headers=auth_header(employee))
    # Access JWT still valid until expiry; body must stay secret-free.
    if me.status_code == 200:
        body = me.json()
        assert "password_hash" not in body
        assert "password" not in body

    async with _uow_factory() as uow:
        await uow.enter_platform()
        row = await uow.employees.get_by_id(employee.id)
        assert row is not None
        assert verify_password(_NEW, row.password_hash)
        assert not verify_password(_PASSWORD, row.password_hash)

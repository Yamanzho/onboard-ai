"""Password hashing: Argon2id + legacy PBKDF2 verification / upgrade."""

from __future__ import annotations

import hashlib
import secrets
from uuid import uuid4

import pytest
from httpx import AsyncClient

from app.core.security import (
    hash_password,
    password_hash_needs_upgrade,
    verify_password,
)
from app.db.enums import EmployeeStatus
from app.db.models.employee import Employee
from tests.conftest import _uow_factory, auth_header


def _legacy_pbkdf2(password: str, *, iterations: int = 120_000) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt.encode("utf-8"),
        iterations,
    )
    return f"pbkdf2_sha256${iterations}${salt}${digest.hex()}"


def test_argon2id_hash_and_verify() -> None:
    password = f"Argon2-Test-{uuid4().hex}!"
    digest = hash_password(password)
    assert digest.startswith("$argon2id$")
    assert verify_password(password, digest) is True
    assert verify_password("wrong-password", digest) is False
    assert password not in digest
    assert password_hash_needs_upgrade(digest) is False


def test_legacy_pbkdf2_still_verifies_and_needs_upgrade() -> None:
    password = f"Legacy-Test-{uuid4().hex}!"
    legacy = _legacy_pbkdf2(password)
    assert verify_password(password, legacy) is True
    assert verify_password("nope", legacy) is False
    assert password_hash_needs_upgrade(legacy) is True


@pytest.mark.asyncio
async def test_login_upgrades_pbkdf2_hash_transparently(
    api_client: AsyncClient,
    company_a,
) -> None:
    password = f"Upgrade-Me-{uuid4().hex}!"
    legacy = _legacy_pbkdf2(password)
    async with _uow_factory() as uow:
        await uow.enter_platform()
        employee = await uow.employees.create(
            Employee(
                company_id=company_a.id,
                full_name="Hash Upgrade",
                email=f"upgrade-{uuid4().hex[:8]}@example.com",
                role="employee",
                status=EmployeeStatus.ACTIVE.value,
                password_hash=legacy,
                telegram_user_id=uuid4().int % 1_000_000_000 + 6000,
            )
        )
        await uow.commit()
        employee_id = employee.id

    login = await api_client.post(
        "/api/v1/auth/login",
        data={"username": str(employee_id), "password": password},
    )
    assert login.status_code == 200, login.text

    async with _uow_factory() as uow:
        await uow.enter_tenant(company_a.id)
        row = await uow.employees.get_by_id(employee_id)
        assert row is not None
        assert row.password_hash is not None
        assert row.password_hash.startswith("$argon2id$")
        assert verify_password(password, row.password_hash) is True
        assert password not in (row.password_hash or "")

    # Second login still works with the upgraded hash.
    again = await api_client.post(
        "/api/v1/auth/login",
        data={"username": str(employee_id), "password": password},
    )
    assert again.status_code == 200


@pytest.mark.asyncio
async def test_password_change_stores_argon2id(
    api_client: AsyncClient,
    employee_a: Employee,
) -> None:
    # Ensure employee has a known Argon2 hash first.
    password = f"Current-{uuid4().hex}!"
    new_password = f"NewPass-{uuid4().hex}!"
    async with _uow_factory() as uow:
        await uow.enter_tenant(employee_a.company_id)
        await uow.employees.update(
            employee_a.id,
            password_hash=hash_password(password),
            status=EmployeeStatus.ACTIVE.value,
        )
        await uow.commit()

    res = await api_client.post(
        "/api/v1/auth/password",
        headers=auth_header(employee_a),
        json={
            "current_password": password,
            "new_password": new_password,
            "confirm_password": new_password,
        },
    )
    assert res.status_code == 204, res.text

    async with _uow_factory() as uow:
        await uow.enter_tenant(employee_a.company_id)
        row = await uow.employees.get_by_id(employee_a.id)
        assert row is not None
        assert row.password_hash is not None
        assert row.password_hash.startswith("$argon2id$")
        assert verify_password(new_password, row.password_hash) is True
        assert verify_password(password, row.password_hash) is False

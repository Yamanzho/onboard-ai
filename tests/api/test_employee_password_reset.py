"""Sprint 1.3: Admin/HR password reset for ACTIVE employees."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import select

from app.core.security import hash_password, hash_token, verify_password
from app.db.enums import EmployeeRole, EmployeeStatus, InvitePurpose
from app.db.models.employee import Employee
from app.db.models.employee_invite import EmployeeInvite
from app.db.models.refresh_session import RefreshSession
from app.services.refresh_session import SUBJECT_EMPLOYEE, RefreshSessionService
from tests.conftest import auth_header, _uow_factory, tenant_tokens_from_response

_PASSWORD = "ResetPass1!"
_NEW = "ResetPass2!"


async def _active(
    company_id,
    *,
    role: str = EmployeeRole.EMPLOYEE.value,
    email: str | None = None,
) -> Employee:
    async with _uow_factory() as uow:
        await uow.enter_platform()
        employee = await uow.employees.create(
            Employee(
                company_id=company_id,
                telegram_user_id=uuid4().int % 1_000_000_000 + 4000,
                full_name="Reset Target",
                email=email or f"reset-{uuid4().hex[:8]}@example.com",
                role=role,
                status=EmployeeStatus.ACTIVE.value,
                password_hash=hash_password(_PASSWORD),
            ),
        )
        await uow.commit()
        return employee


async def _count_sessions(subject_id) -> int:
    async with _uow_factory() as uow:
        await uow.enter_platform()
        stmt = select(RefreshSession).where(
            RefreshSession.subject_type == SUBJECT_EMPLOYEE,
            RefreshSession.subject_id == subject_id,
            RefreshSession.revoked_at.is_(None),
        )
        return len(list((await uow.session.scalars(stmt)).all()))


async def _login(api_client: AsyncClient, employee_id, password: str = _PASSWORD) -> dict:
    response = await api_client.post(
        "/api/v1/auth/login",
        data={"username": str(employee_id), "password": password},
    )
    assert response.status_code == 200, response.text
    return tenant_tokens_from_response(response)


def _extract_token_from_url(url: str) -> str:
    assert "#" in url
    return url.rsplit("#", 1)[1]


async def test_admin_can_initiate_reset_revokes_sessions(
    api_client: AsyncClient,
    company_a,
    admin_a: Employee,
) -> None:
    target = await _active(company_a.id)
    tokens = await _login(api_client, target.id)
    await RefreshSessionService().issue(
        subject_type=SUBJECT_EMPLOYEE,
        subject_id=target.id,
        role=target.role,
        company_id=target.company_id,
    )
    assert await _count_sessions(target.id) >= 2

    res = await api_client.post(
        f"/api/v1/employees/{target.id}/password/reset",
        headers=auth_header(admin_a),
    )
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["delivery"] == "manual_url"
    assert body["reset_url"]
    assert "password" not in body
    assert "token" not in body or body.get("token") is None
    assert await _count_sessions(target.id) == 0

    replay = await api_client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": tokens["refresh_token"]},
    )
    assert replay.status_code == 401


async def test_hr_can_reset_employee_not_peer_hr(
    api_client: AsyncClient,
    company_a,
    hr_a: Employee,
) -> None:
    employee = await _active(company_a.id)
    peer_hr = await _active(company_a.id, role=EmployeeRole.HR.value)

    ok = await api_client.post(
        f"/api/v1/employees/{employee.id}/password/reset",
        headers=auth_header(hr_a),
    )
    assert ok.status_code == 200, ok.text

    denied = await api_client.post(
        f"/api/v1/employees/{peer_hr.id}/password/reset",
        headers=auth_header(hr_a),
    )
    assert denied.status_code == 403, denied.text


async def test_password_reset_token_single_use_and_confirm(
    api_client: AsyncClient,
    company_a,
    admin_a: Employee,
) -> None:
    target = await _active(company_a.id)
    initiated = await api_client.post(
        f"/api/v1/employees/{target.id}/password/reset",
        headers=auth_header(admin_a),
    )
    assert initiated.status_code == 200, initiated.text
    token = _extract_token_from_url(initiated.json()["reset_url"])

    preview = await api_client.post(
        "/api/v1/auth/password/reset/preview",
        json={"token": token},
    )
    assert preview.status_code == 200, preview.text
    assert preview.json()["purpose"] == InvitePurpose.PASSWORD_RESET.value

    confirm = await api_client.post(
        "/api/v1/auth/password/reset/confirm",
        json={
            "token": token,
            "new_password": _NEW,
            "confirm_password": _NEW,
        },
    )
    assert confirm.status_code == 200, confirm.text
    body = confirm.json()
    assert "password_hash" not in body
    assert body["role"] == EmployeeRole.EMPLOYEE.value
    assert body["status"] == EmployeeStatus.ACTIVE.value

    reuse = await api_client.post(
        "/api/v1/auth/password/reset/confirm",
        json={
            "token": token,
            "new_password": "AnotherPass9!",
            "confirm_password": "AnotherPass9!",
        },
    )
    assert reuse.status_code == 400

    login = await api_client.post(
        "/api/v1/auth/login",
        data={"username": str(target.id), "password": _NEW},
    )
    assert login.status_code == 200, login.text


async def test_expired_reset_token_denied(
    api_client: AsyncClient,
    company_a,
) -> None:
    target = await _active(company_a.id)
    raw = f"expired-reset-{uuid4().hex}"
    async with _uow_factory() as uow:
        await uow.enter_platform()
        await uow.employee_invites.create(
            EmployeeInvite(
                company_id=company_a.id,
                employee_id=target.id,
                token_hash=hash_token(raw),
                expires_at=datetime.now(UTC) - timedelta(hours=1),
                invited_email=target.email,
                purpose=InvitePurpose.PASSWORD_RESET.value,
            ),
        )
        await uow.commit()

    preview = await api_client.post(
        "/api/v1/auth/password/reset/preview",
        json={"token": raw},
    )
    assert preview.status_code == 400
    assert "expired" in preview.json()["detail"].lower()


async def test_reset_token_not_logged(
    api_client: AsyncClient,
    company_a,
    admin_a: Employee,
    caplog: pytest.LogCaptureFixture,
) -> None:
    target = await _active(company_a.id)
    with caplog.at_level("INFO"):
        res = await api_client.post(
            f"/api/v1/employees/{target.id}/password/reset",
            headers=auth_header(admin_a),
        )
    assert res.status_code == 200, res.text
    token = _extract_token_from_url(res.json()["reset_url"])
    joined = "\n".join(r.message for r in caplog.records)
    assert token not in joined
    assert _PASSWORD not in joined
    assert _NEW not in joined
    # Email path must omit body (tokens live in the URL body).
    assert "body_omitted=true" in joined


async def test_cross_tenant_reset_denied(
    api_client: AsyncClient,
    company_b,
    admin_a: Employee,
) -> None:
    foreign = await _active(company_b.id)
    res = await api_client.post(
        f"/api/v1/employees/{foreign.id}/password/reset",
        headers=auth_header(admin_a),
    )
    assert res.status_code == 404


async def test_onboarding_invite_still_rejected_for_active(
    api_client: AsyncClient,
    company_a,
) -> None:
    """ACTIVE password reset must not reuse onboarding invite accept."""
    target = await _active(company_a.id)
    raw = f"onboard-as-reset-{uuid4().hex}"
    async with _uow_factory() as uow:
        await uow.enter_platform()
        await uow.employee_invites.create(
            EmployeeInvite(
                company_id=company_a.id,
                employee_id=target.id,
                token_hash=hash_token(raw),
                expires_at=datetime.now(UTC) + timedelta(hours=2),
                invited_email=target.email,
                purpose=InvitePurpose.EMPLOYEE.value,
            ),
        )
        await uow.commit()

    accept = await api_client.post(
        "/api/v1/auth/invite/accept",
        json={"token": raw, "password": _NEW},
    )
    assert accept.status_code == 400

    async with _uow_factory() as uow:
        await uow.enter_platform()
        row = await uow.employees.get_by_id(target.id)
        assert row is not None
        assert verify_password(_PASSWORD, row.password_hash)

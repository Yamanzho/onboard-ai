"""P1: onboarding invites must not reset passwords for ACTIVE employees."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from httpx import AsyncClient

from app.core.exceptions import ValidationError
from app.core.security import hash_password, hash_token, verify_password
from app.db.enums import EmployeeRole, EmployeeStatus
from app.db.models.employee import Employee
from app.db.models.employee_invite import EmployeeInvite
from app.services.platform import PlatformService
from app.services.platform_management import InviteService
from app.services.refresh_session import SUBJECT_EMPLOYEE, RefreshSessionService
from tests.conftest import _uow_factory, tenant_tokens_from_response

_OLD_PASSWORD = "OldSecurePass1!"
_NEW_PASSWORD = "NewSecurePass1!"
_INVITE_ONLY_MSG = "Invite is only valid for invited employees"
_RESEND_ONLY_MSG = "Onboarding invites can only be resent to invited employees"
_SEND_ONLY_MSG = "Onboarding invites can only be sent to invited employees"


async def _make_employee(
    company_id,
    *,
    status: str,
    password: str | None = None,
    email: str | None = None,
    telegram_user_id: int | None = None,
) -> Employee:
    async with _uow_factory() as uow:
        await uow.enter_platform()
        employee = await uow.employees.create(
            Employee(
                company_id=company_id,
                telegram_user_id=telegram_user_id or (uuid4().int % 1_000_000_000 + 7000),
                full_name=f"Invite Test {status}",
                email=email or f"{status}-{uuid4().hex[:8]}@example.com",
                role=EmployeeRole.EMPLOYEE.value,
                status=status,
                password_hash=hash_password(password) if password else None,
            ),
        )
        await uow.commit()
        return employee


async def _make_invite(employee_id, *, company_id, token: str, email: str) -> str:
    async with _uow_factory() as uow:
        await uow.enter_platform()
        await uow.employee_invites.create(
            EmployeeInvite(
                company_id=company_id,
                employee_id=employee_id,
                token_hash=hash_token(token),
                expires_at=datetime.now(UTC) + timedelta(hours=24),
                invited_email=email,
            ),
        )
        await uow.commit()
    return token


@pytest.mark.asyncio
async def test_active_employee_cannot_accept_onboarding_invite(
    api_client: AsyncClient,
    company_a,
) -> None:
    employee = await _make_employee(
        company_a.id,
        status=EmployeeStatus.ACTIVE.value,
        password=_OLD_PASSWORD,
    )
    token = f"active-takeover-{uuid4().hex}"
    await _make_invite(employee.id, company_id=company_a.id, token=token, email=employee.email)

    response = await api_client.post(
        "/api/v1/auth/invite/accept",
        json={"token": token, "password": _NEW_PASSWORD},
    )
    assert response.status_code == 400, response.text
    assert _INVITE_ONLY_MSG in response.json()["detail"]

    async with _uow_factory() as uow:
        await uow.enter_platform()
        refreshed = await uow.employees.get_by_id(employee.id)
        assert refreshed is not None
        assert refreshed.status == EmployeeStatus.ACTIVE.value
        assert verify_password(_OLD_PASSWORD, refreshed.password_hash)
        assert not verify_password(_NEW_PASSWORD, refreshed.password_hash or "")


@pytest.mark.asyncio
async def test_archived_employee_cannot_accept_onboarding_invite(
    api_client: AsyncClient,
    company_a,
) -> None:
    employee = await _make_employee(
        company_a.id,
        status=EmployeeStatus.ARCHIVED.value,
        password=_OLD_PASSWORD,
    )
    token = f"archived-takeover-{uuid4().hex}"
    await _make_invite(employee.id, company_id=company_a.id, token=token, email=employee.email)

    response = await api_client.post(
        "/api/v1/auth/invite/accept",
        json={"token": token, "password": _NEW_PASSWORD},
    )
    assert response.status_code == 400, response.text
    assert _INVITE_ONLY_MSG in response.json()["detail"]

    async with _uow_factory() as uow:
        await uow.enter_platform()
        refreshed = await uow.employees.get_by_id(employee.id)
        assert refreshed is not None
        assert refreshed.status == EmployeeStatus.ARCHIVED.value
        assert verify_password(_OLD_PASSWORD, refreshed.password_hash)


@pytest.mark.asyncio
async def test_invited_employee_can_accept_sets_password_and_becomes_active(
    api_client: AsyncClient,
    company_a,
) -> None:
    employee = await _make_employee(
        company_a.id,
        status=EmployeeStatus.INVITED.value,
        password=None,
    )
    token = f"invited-ok-{uuid4().hex}"
    await _make_invite(employee.id, company_id=company_a.id, token=token, email=employee.email)

    accept = await api_client.post(
        "/api/v1/auth/invite/accept",
        json={"token": token, "password": _NEW_PASSWORD},
    )
    assert accept.status_code == 200, accept.text
    body = accept.json()
    assert body["status"] == EmployeeStatus.ACTIVE.value
    assert body["id"] == str(employee.id)

    async with _uow_factory() as uow:
        await uow.enter_platform()
        refreshed = await uow.employees.get_by_id(employee.id)
        assert refreshed is not None
        assert refreshed.status == EmployeeStatus.ACTIVE.value
        assert verify_password(_NEW_PASSWORD, refreshed.password_hash)

    login = await api_client.post(
        "/api/v1/auth/login",
        data={"username": str(employee.id), "password": _NEW_PASSWORD},
    )
    assert login.status_code == 200, login.text


@pytest.mark.asyncio
async def test_accept_overwrites_preexisting_hash_only_when_invited(
    api_client: AsyncClient,
    company_a,
) -> None:
    """INVITED may carry a leftover hash; accept sets the initial password."""
    employee = await _make_employee(
        company_a.id,
        status=EmployeeStatus.INVITED.value,
        password=_OLD_PASSWORD,
    )
    token = f"invited-overwrite-{uuid4().hex}"
    await _make_invite(employee.id, company_id=company_a.id, token=token, email=employee.email)

    accept = await api_client.post(
        "/api/v1/auth/invite/accept",
        json={"token": token, "password": _NEW_PASSWORD},
    )
    assert accept.status_code == 200, accept.text

    async with _uow_factory() as uow:
        await uow.enter_platform()
        refreshed = await uow.employees.get_by_id(employee.id)
        assert refreshed is not None
        assert verify_password(_NEW_PASSWORD, refreshed.password_hash)
        assert not verify_password(_OLD_PASSWORD, refreshed.password_hash or "")

    old_login = await api_client.post(
        "/api/v1/auth/login",
        data={"username": str(employee.id), "password": _OLD_PASSWORD},
    )
    assert old_login.status_code == 401

    new_login = await api_client.post(
        "/api/v1/auth/login",
        data={"username": str(employee.id), "password": _NEW_PASSWORD},
    )
    assert new_login.status_code == 200, new_login.text


@pytest.mark.asyncio
async def test_active_employee_cannot_resend_or_receive_onboarding_invite(
    company_a,
) -> None:
    employee = await _make_employee(
        company_a.id,
        status=EmployeeStatus.ACTIVE.value,
        password=_OLD_PASSWORD,
    )
    platform = PlatformService(uow_factory=_uow_factory)
    invites = InviteService(uow_factory=_uow_factory)

    with pytest.raises(ValidationError, match=_RESEND_ONLY_MSG):
        await platform.resend_invite(employee.id)

    with pytest.raises(ValidationError, match=_SEND_ONLY_MSG):
        await invites.create_and_send_invite(
            employee=employee,
            invited_email=employee.email,
            company_name=company_a.name,
        )


@pytest.mark.asyncio
async def test_accepted_invite_cannot_be_replayed(
    api_client: AsyncClient,
    company_a,
) -> None:
    employee = await _make_employee(
        company_a.id,
        status=EmployeeStatus.INVITED.value,
    )
    token = f"replay-{uuid4().hex}"
    await _make_invite(employee.id, company_id=company_a.id, token=token, email=employee.email)

    first = await api_client.post(
        "/api/v1/auth/invite/accept",
        json={"token": token, "password": _NEW_PASSWORD},
    )
    assert first.status_code == 200, first.text

    replay = await api_client.post(
        "/api/v1/auth/invite/accept",
        json={"token": token, "password": "AnotherPass1!"},
    )
    assert replay.status_code == 400, replay.text
    assert "already used" in replay.json()["detail"]


@pytest.mark.asyncio
async def test_sibling_invites_invalidated_on_accept(
    api_client: AsyncClient,
    company_a,
) -> None:
    employee = await _make_employee(
        company_a.id,
        status=EmployeeStatus.INVITED.value,
    )
    t1 = f"sib-one-{uuid4().hex}"
    t2 = f"sib-two-{uuid4().hex}"
    await _make_invite(employee.id, company_id=company_a.id, token=t1, email=employee.email)
    await _make_invite(employee.id, company_id=company_a.id, token=t2, email=employee.email)

    ok = await api_client.post(
        "/api/v1/auth/invite/accept",
        json={"token": t1, "password": _NEW_PASSWORD},
    )
    assert ok.status_code == 200, ok.text

    sibling = await api_client.post(
        "/api/v1/auth/invite/accept",
        json={"token": t2, "password": "AttackerPass1!"},
    )
    assert sibling.status_code == 400, sibling.text

    async with _uow_factory() as uow:
        await uow.enter_platform()
        for raw in (t1, t2):
            row = await uow.employee_invites.get_by_token_hash(hash_token(raw))
            assert row is not None
            assert row.used_at is not None
        refreshed = await uow.employees.get_by_id(employee.id)
        assert refreshed is not None
        assert verify_password(_NEW_PASSWORD, refreshed.password_hash)


@pytest.mark.asyncio
async def test_accept_revokes_existing_refresh_sessions_for_subject(
    api_client: AsyncClient,
    company_a,
) -> None:
    employee = await _make_employee(
        company_a.id,
        status=EmployeeStatus.INVITED.value,
    )
    issued = await RefreshSessionService().issue(
        subject_type=SUBJECT_EMPLOYEE,
        subject_id=employee.id,
        role=employee.role,
        company_id=employee.company_id,
    )
    raw_refresh = issued.tokens.refresh_token

    token = f"revoke-sess-{uuid4().hex}"
    await _make_invite(employee.id, company_id=company_a.id, token=token, email=employee.email)

    accept = await api_client.post(
        "/api/v1/auth/invite/accept",
        json={"token": token, "password": _NEW_PASSWORD},
    )
    assert accept.status_code == 200, accept.text

    async with _uow_factory() as uow:
        await uow.enter_platform()
        session = await uow.refresh_sessions.get_by_token_hash_for_update(
            hash_token(raw_refresh),
        )
        # get_by_token_hash_for_update exists; also check via revoke path
        assert session is not None
        assert session.revoked_at is not None

    refresh = await api_client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": raw_refresh},
    )
    assert refresh.status_code == 401


@pytest.mark.asyncio
async def test_accept_does_not_revoke_other_employees_sessions(
    api_client: AsyncClient,
    company_a,
) -> None:
    victim = await _make_employee(
        company_a.id,
        status=EmployeeStatus.INVITED.value,
        email=f"victim-{uuid4().hex[:8]}@example.com",
    )
    other = await _make_employee(
        company_a.id,
        status=EmployeeStatus.ACTIVE.value,
        password=_OLD_PASSWORD,
        email=f"other-{uuid4().hex[:8]}@example.com",
    )
    other_session = await RefreshSessionService().issue(
        subject_type=SUBJECT_EMPLOYEE,
        subject_id=other.id,
        role=other.role,
        company_id=other.company_id,
    )

    token = f"scoped-revoke-{uuid4().hex}"
    await _make_invite(victim.id, company_id=company_a.id, token=token, email=victim.email)

    accept = await api_client.post(
        "/api/v1/auth/invite/accept",
        json={"token": token, "password": _NEW_PASSWORD},
    )
    assert accept.status_code == 200, accept.text

    refresh = await api_client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": other_session.tokens.refresh_token},
    )
    assert refresh.status_code == 200, refresh.text


@pytest.mark.asyncio
async def test_invite_token_does_not_activate_cross_company_employee(
    api_client: AsyncClient,
    company_a,
    company_b,
) -> None:
    """Invite always binds to employee_id on the invite row (tenant-safe)."""
    emp_a = await _make_employee(
        company_a.id,
        status=EmployeeStatus.INVITED.value,
        email=f"a-{uuid4().hex[:8]}@example.com",
    )
    emp_b = await _make_employee(
        company_b.id,
        status=EmployeeStatus.INVITED.value,
        email=f"b-{uuid4().hex[:8]}@example.com",
        password=None,
    )
    token = f"cross-co-{uuid4().hex}"
    await _make_invite(emp_a.id, company_id=company_a.id, token=token, email=emp_a.email)

    accept = await api_client.post(
        "/api/v1/auth/invite/accept",
        json={"token": token, "password": _NEW_PASSWORD},
    )
    assert accept.status_code == 200, accept.text
    assert accept.json()["id"] == str(emp_a.id)
    assert accept.json()["company_id"] == str(company_a.id)

    async with _uow_factory() as uow:
        await uow.enter_platform()
        still_invited = await uow.employees.get_by_id(emp_b.id)
        assert still_invited is not None
        assert still_invited.status == EmployeeStatus.INVITED.value
        assert still_invited.password_hash is None


@pytest.mark.asyncio
async def test_normal_login_unchanged_for_active_employee(
    api_client: AsyncClient,
    company_a,
) -> None:
    employee = await _make_employee(
        company_a.id,
        status=EmployeeStatus.ACTIVE.value,
        password=_OLD_PASSWORD,
    )
    login = await api_client.post(
        "/api/v1/auth/login",
        data={"username": str(employee.id), "password": _OLD_PASSWORD},
    )
    assert login.status_code == 200, login.text
    assert "access_token" not in login.json()
    assert "refresh_token" not in login.json()
    assert tenant_tokens_from_response(login)["access_token"]


@pytest.mark.asyncio
async def test_preview_rejects_invite_for_active_employee(
    api_client: AsyncClient,
    company_a,
) -> None:
    employee = await _make_employee(
        company_a.id,
        status=EmployeeStatus.ACTIVE.value,
        password=_OLD_PASSWORD,
    )
    token = f"preview-active-{uuid4().hex}"
    await _make_invite(employee.id, company_id=company_a.id, token=token, email=employee.email)

    preview = await api_client.post(
        "/api/v1/auth/invite/preview",
        json={"token": token},
    )
    assert preview.status_code == 400, preview.text
    assert _INVITE_ONLY_MSG in preview.json()["detail"]

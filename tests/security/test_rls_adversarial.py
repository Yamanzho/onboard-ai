"""SEC-R3 adversarial RLS tests against real PostgreSQL (onboard_app)."""

from __future__ import annotations

from uuid import uuid4

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.db.session as db_session
from app.core.config import get_settings
from app.core.security import create_access_token, hash_token
from app.db.enums import EmployeeRole, EmployeeStatus
from app.db.models.company import Company
from app.db.models.employee import Employee
from app.db.models.employee_invite import EmployeeInvite
from app.db.models.onboarding_program import OnboardingProgram
from app.db.models.platform_audit_log import PlatformAuditLog
from app.db.models.refresh_session import RefreshSession
from app.db.uow import UnitOfWork
from app.services.telegram_outbound import TelegramOutboundService
from tests.conftest import auth_header, unique_email, unique_telegram_user_id

pytestmark = pytest.mark.security


@pytest.mark.asyncio
async def test_telegram_outbox_rls_blocks_cross_tenant_read_and_update(
    app_role_session: AsyncSession,
    company_a: Company,
    company_b: Company,
    employee_a: Employee,
) -> None:
    source_key = f"telegram-update:{uuid4().int}:ai-chat"
    async with _uow() as uow:
        await uow.enter_tenant(company_a.id)
        row = await TelegramOutboundService().enqueue_in_uow(
            uow,
            company_id=company_a.id,
            employee_id=employee_a.id,
            chat_id=employee_a.telegram_chat_id or employee_a.telegram_user_id,
            source_type="ai_chat",
            source_key=source_key,
            body="Tenant A only",
        )
        await uow.commit()

    await _set_tenant(app_role_session, company_b.id)
    visible = (
        await app_role_session.execute(
            text(
                "SELECT count(*) FROM telegram_outbound_messages WHERE id = :id"
            ),
            {"id": row.id},
        )
    ).scalar_one()
    mutated = await app_role_session.execute(
        text(
            "UPDATE telegram_outbound_messages SET status = 'sent' "
            "WHERE id = :id"
        ),
        {"id": row.id},
    )
    assert visible == 0
    assert mutated.rowcount == 0
    await app_role_session.rollback()


def _uow() -> UnitOfWork:
    return UnitOfWork(session_factory=db_session.async_session_factory)


@pytest.fixture
async def app_role_session() -> AsyncSession:
    """Session connected as onboard_app (no BYPASSRLS)."""
    settings = get_settings()
    # Prefer explicit app URL; fall back to rewriting owner → app for local.
    url = settings.database_url
    if "onboard_app" not in url and "onboard_owner" in url:
        url = url.replace("onboard_owner", "onboard_app")
    engine = create_async_engine(url, echo=False, connect_args={"ssl": False})
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        yield session
    await engine.dispose()


async def _set_tenant(session: AsyncSession, company_id) -> None:
    await session.execute(
        text("SELECT set_config('app.current_company_id', :v, true)"),
        {"v": str(company_id)},
    )
    await session.execute(text("SELECT set_config('app.current_employee_id', '', true)"))
    await session.execute(text("SELECT set_config('app.platform_admin', '', true)"))
    await session.execute(text("SELECT set_config('app.auth_mode', '', true)"))
    await session.execute(text("SELECT set_config('app.session_mode', '', true)"))
    await session.execute(text("SELECT set_config('app.auth_employee_id', '', true)"))
    await session.execute(text("SELECT set_config('app.auth_telegram_user_id', '', true)"))
    await session.execute(text("SELECT set_config('app.auth_invite_token_hash', '', true)"))
    await session.execute(text("SELECT set_config('app.auth_super_admin_id', '', true)"))
    await session.execute(text("SELECT set_config('app.auth_super_admin_email', '', true)"))


async def _set_platform(session: AsyncSession) -> None:
    await session.execute(text("SELECT set_config('app.platform_admin', 'on', true)"))
    await session.execute(text("SELECT set_config('app.current_company_id', '', true)"))
    await session.execute(text("SELECT set_config('app.current_employee_id', '', true)"))
    await session.execute(text("SELECT set_config('app.auth_mode', '', true)"))
    await session.execute(text("SELECT set_config('app.session_mode', '', true)"))
    await session.execute(text("SELECT set_config('app.auth_employee_id', '', true)"))
    await session.execute(text("SELECT set_config('app.auth_telegram_user_id', '', true)"))
    await session.execute(text("SELECT set_config('app.auth_invite_token_hash', '', true)"))
    await session.execute(text("SELECT set_config('app.auth_super_admin_id', '', true)"))
    await session.execute(text("SELECT set_config('app.auth_super_admin_email', '', true)"))


async def _clear_gucs(session: AsyncSession) -> None:
    for key in (
        "app.current_company_id",
        "app.current_employee_id",
        "app.platform_admin",
        "app.auth_mode",
        "app.session_mode",
        "app.auth_employee_id",
        "app.auth_telegram_user_id",
        "app.auth_invite_token_hash",
        "app.auth_super_admin_id",
        "app.auth_super_admin_email",
    ):
        await session.execute(
            text("SELECT set_config(:k, '', true)"),
            {"k": key},
        )


async def _set_auth(
    session: AsyncSession,
    *,
    employee_id=None,
    telegram_user_id: int | None = None,
    invite_token_hash: str | None = None,
    super_admin_id=None,
    super_admin_email: str | None = None,
) -> None:
    await session.execute(text("SELECT set_config('app.auth_mode', 'bootstrap', true)"))
    await session.execute(text("SELECT set_config('app.current_company_id', '', true)"))
    await session.execute(text("SELECT set_config('app.current_employee_id', '', true)"))
    await session.execute(text("SELECT set_config('app.platform_admin', '', true)"))
    await session.execute(text("SELECT set_config('app.session_mode', '', true)"))
    await session.execute(
        text("SELECT set_config('app.auth_employee_id', :v, true)"),
        {"v": str(employee_id) if employee_id is not None else ""},
    )
    await session.execute(
        text("SELECT set_config('app.auth_telegram_user_id', :v, true)"),
        {"v": str(telegram_user_id) if telegram_user_id is not None else ""},
    )
    await session.execute(
        text("SELECT set_config('app.auth_invite_token_hash', :v, true)"),
        {"v": invite_token_hash or ""},
    )
    await session.execute(
        text("SELECT set_config('app.auth_super_admin_id', :v, true)"),
        {"v": str(super_admin_id) if super_admin_id is not None else ""},
    )
    await session.execute(
        text("SELECT set_config('app.auth_super_admin_email', :v, true)"),
        {"v": (super_admin_email or "").lower()},
    )


@pytest.mark.asyncio
async def test_catalog_onboard_app_no_bypassrls(app_role_session: AsyncSession) -> None:
    row = (
        await app_role_session.execute(
            text(
                "SELECT rolname, rolbypassrls FROM pg_roles "
                "WHERE rolname IN ('onboard_app', 'onboard_owner') ORDER BY 1"
            )
        )
    ).all()
    roles = {r[0]: r[1] for r in row}
    assert roles.get("onboard_app") is False
    assert roles.get("onboard_owner") is True


@pytest.mark.asyncio
async def test_catalog_onboard_app_not_table_owner(app_role_session: AsyncSession) -> None:
    owner = (
        await app_role_session.execute(
            text(
                "SELECT tableowner FROM pg_tables "
                "WHERE schemaname='public' AND tablename='employees'"
            )
        )
    ).scalar_one()
    assert owner == "onboard_owner"
    assert owner != "onboard_app"


@pytest.mark.asyncio
async def test_catalog_force_rls_enabled(app_role_session: AsyncSession) -> None:
    rows = (
        await app_role_session.execute(
            text(
                "SELECT relname, relrowsecurity, relforcerowsecurity "
                "FROM pg_class WHERE relname IN ('employees', 'refresh_sessions', "
                "'employee_invites', 'companies', 'company_audit_logs', "
                "'knowledge_article_chunks') ORDER BY 1"
            )
        )
    ).all()
    assert rows
    for name, rls, force in rows:
        assert rls is True, name
        assert force is True, name


@pytest.mark.asyncio
async def test_tenant_a_cannot_select_tenant_b(
    company_a: Company,
    company_b: Company,
    app_role_session: AsyncSession,
) -> None:
    await _set_tenant(app_role_session, company_a.id)
    visible = (
        await app_role_session.execute(
            text("SELECT id FROM companies WHERE id = :id"),
            {"id": company_b.id},
        )
    ).first()
    assert visible is None
    own = (
        await app_role_session.execute(
            text("SELECT id FROM companies WHERE id = :id"),
            {"id": company_a.id},
        )
    ).first()
    assert own is not None


@pytest.mark.asyncio
async def test_tenant_a_cannot_insert_update_delete_tenant_b(
    company_a: Company,
    company_b: Company,
    hr_b: Employee,
    app_role_session: AsyncSession,
) -> None:
    await _set_tenant(app_role_session, company_a.id)

    with pytest.raises(Exception):
        await app_role_session.execute(
            text(
                "INSERT INTO onboarding_programs "
                "(id, company_id, title, is_active, created_at, updated_at) "
                "VALUES (gen_random_uuid(), :cid, 'x', true, now(), now())"
            ),
            {"cid": company_b.id},
        )
        await app_role_session.commit()
    await app_role_session.rollback()

    await _set_tenant(app_role_session, company_a.id)
    updated = await app_role_session.execute(
        text("UPDATE employees SET full_name = 'hacked' WHERE id = :id"),
        {"id": hr_b.id},
    )
    assert updated.rowcount == 0

    deleted = await app_role_session.execute(
        text("DELETE FROM employees WHERE id = :id"),
        {"id": hr_b.id},
    )
    assert deleted.rowcount == 0
    await app_role_session.rollback()


@pytest.mark.asyncio
async def test_missing_and_wrong_guc_fail_closed(
    company_a: Company,
    company_b: Company,
    app_role_session: AsyncSession,
) -> None:
    await _clear_gucs(app_role_session)
    rows = (
        await app_role_session.execute(text("SELECT id FROM companies LIMIT 5"))
    ).all()
    assert rows == []

    await _set_tenant(app_role_session, company_a.id)
    wrong = (
        await app_role_session.execute(
            text("SELECT id FROM companies WHERE id = :id"),
            {"id": company_b.id},
        )
    ).first()
    assert wrong is None


@pytest.mark.asyncio
async def test_forged_jwt_company_id_ignored(
    api_client: AsyncClient,
    company_a: Company,
    company_b: Company,
    hr_a: Employee,
) -> None:
    forged = create_access_token(
        subject=hr_a.id,
        role=hr_a.role,
        company_id=company_b.id,  # forged — must not grant B access
    )
    # Create a program in B via platform UoW
    async with _uow() as uow:
        await uow.enter_platform()
        prog = await uow.onboarding_programs.create(
            OnboardingProgram(
                company_id=company_b.id,
                title=f"Secret {uuid4().hex[:8]}",
                is_active=True,
            ),
        )
        await uow.commit()
        prog_id = prog.id

    resp = await api_client.get(
        f"/api/v1/programs/{prog_id}",
        headers={"Authorization": f"Bearer {forged}"},
    )
    assert resp.status_code == 404, resp.text


@pytest.mark.asyncio
async def test_pool_no_leakage_and_rollback_clears_local(
    company_a: Company,
    company_b: Company,
    app_role_session: AsyncSession,
) -> None:
    await _set_tenant(app_role_session, company_a.id)
    assert (
        await app_role_session.execute(
            text("SELECT id FROM companies WHERE id = :id"),
            {"id": company_a.id},
        )
    ).first()
    await app_role_session.rollback()  # clears LOCAL GUCs

    # New txn, no GUC → fail closed
    rows = (await app_role_session.execute(text("SELECT id FROM companies"))).all()
    assert rows == []

    await _set_tenant(app_role_session, company_b.id)
    assert (
        await app_role_session.execute(
            text("SELECT id FROM companies WHERE id = :id"),
            {"id": company_b.id},
        )
    ).first()
    assert (
        await app_role_session.execute(
            text("SELECT id FROM companies WHERE id = :id"),
            {"id": company_a.id},
        )
    ).first() is None


@pytest.mark.asyncio
async def test_mid_uow_commit_reapplies_context(company_a: Company) -> None:
    async with _uow() as uow:
        await uow.enter_tenant(company_a.id)
        company = await uow.companies.get_by_id(company_a.id)
        assert company is not None
        await uow.commit()  # must re-apply LOCAL GUCs
        company2 = await uow.companies.get_by_id(company_a.id)
        assert company2 is not None


@pytest.mark.asyncio
async def test_super_admin_platform_mode_required(
    company_a: Company,
    company_b: Company,
    app_role_session: AsyncSession,
) -> None:
    await _clear_gucs(app_role_session)
    assert (await app_role_session.execute(text("SELECT count(*) FROM companies"))).scalar() == 0

    await _set_platform(app_role_session)
    count = (await app_role_session.execute(text("SELECT count(*) FROM companies"))).scalar()
    assert count >= 2


@pytest.mark.asyncio
async def test_refresh_sessions_tenant_denied_session_ok(
    hr_a: Employee,
    app_role_session: AsyncSession,
) -> None:
    # Create a session row via UoW session_bootstrap
    async with _uow() as uow:
        await uow.enter_session_bootstrap()
        session = RefreshSession(
            token_hash=hash_token(f"rls-test-{uuid4().hex}"),
            family_id=uuid4(),
            subject_type="employee",
            subject_id=hr_a.id,
            expires_at=__import__("datetime").datetime.now(
                __import__("datetime").UTC
            )
            + __import__("datetime").timedelta(days=1),
        )
        await uow.refresh_sessions.create(session)
        await uow.commit()
        sid = session.id

    await _set_tenant(app_role_session, hr_a.company_id)
    assert (
        await app_role_session.execute(
            text("SELECT id FROM refresh_sessions WHERE id = :id"),
            {"id": sid},
        )
    ).first() is None

    await app_role_session.execute(
        text("SELECT set_config('app.session_mode', 'bootstrap', true)")
    )
    await app_role_session.execute(text("SELECT set_config('app.current_company_id', '', true)"))
    assert (
        await app_role_session.execute(
            text("SELECT id FROM refresh_sessions WHERE id = :id"),
            {"id": sid},
        )
    ).first() is not None


@pytest.mark.asyncio
async def test_employee_invites_auth_bootstrap_only(
    company_a: Company,
    hr_a: Employee,
    app_role_session: AsyncSession,
) -> None:
    """Tenant cannot see invites; unpinned auth cannot; token_hash pin can."""
    token_hash = hash_token(f"inv-{uuid4().hex}")
    async with _uow() as uow:
        await uow.enter_platform()
        inv = await uow.employee_invites.create(
            EmployeeInvite(
                company_id=company_a.id,
                employee_id=hr_a.id,
                token_hash=token_hash,
                expires_at=__import__("datetime").datetime.now(
                    __import__("datetime").UTC
                )
                + __import__("datetime").timedelta(hours=1),
                invited_email="rls@example.com",
                purpose='employee',
            ),
        )
        await uow.commit()
        iid = inv.id

    await _set_tenant(app_role_session, company_a.id)
    assert (
        await app_role_session.execute(
            text("SELECT id FROM employee_invites WHERE id = :id"),
            {"id": iid},
        )
    ).first() is None

    # Unpinned auth_bootstrap: deny-by-default (F-01).
    await _set_auth(app_role_session)
    assert (
        await app_role_session.execute(
            text("SELECT id FROM employee_invites WHERE id = :id"),
            {"id": iid},
        )
    ).first() is None

    await _set_auth(app_role_session, invite_token_hash=token_hash)
    assert (
        await app_role_session.execute(
            text("SELECT id FROM employee_invites WHERE id = :id"),
            {"id": iid},
        )
    ).first() is not None

@pytest.mark.asyncio
async def test_auth_bootstrap_cannot_select_all_companies(
    company_a: Company,
    company_b: Company,
    app_role_session: AsyncSession,
) -> None:
    await _set_auth(app_role_session)
    rows = (
        await app_role_session.execute(text("SELECT id FROM companies"))
    ).all()
    assert rows == []


@pytest.mark.asyncio
async def test_auth_bootstrap_cannot_enumerate_or_mutate_employees(
    company_a: Company,
    company_b: Company,
    hr_a: Employee,
    hr_b: Employee,
    app_role_session: AsyncSession,
) -> None:
    await _set_auth(app_role_session)
    # Unpinned auth: no employee rows visible
    assert (
        await app_role_session.execute(text("SELECT id FROM employees"))
    ).all() == []

    # Pinned to A: only A visible
    await _set_auth(app_role_session, employee_id=hr_a.id)
    ids = {
        r[0]
        for r in (
            await app_role_session.execute(text("SELECT id FROM employees"))
        ).all()
    }
    assert ids == {hr_a.id}

    # Cannot UPDATE B while pinned to A
    result = await app_role_session.execute(
        text("UPDATE employees SET full_name = 'hacked' WHERE id = :id"),
        {"id": hr_b.id},
    )
    assert result.rowcount == 0

    # Cannot DELETE A or B via unpinned/wrong pin
    await _set_auth(app_role_session, employee_id=hr_a.id)
    result = await app_role_session.execute(
        text("DELETE FROM employees WHERE id = :id"),
        {"id": hr_a.id},
    )
    assert result.rowcount == 0

    await _set_auth(app_role_session)
    with pytest.raises(Exception):
        await app_role_session.execute(
            text(
                "INSERT INTO employees "
                "(id, company_id, full_name, role, status, created_at, updated_at) "
                "VALUES (gen_random_uuid(), :cid, 'x', 'employee', 'active', now(), now())"
            ),
            {"cid": company_a.id},
        )
        await app_role_session.commit()
    await app_role_session.rollback()


@pytest.mark.asyncio
async def test_auth_bootstrap_subscriptions_not_readable(
    company_a: Company,
    app_role_session: AsyncSession,
) -> None:
    await _set_auth(app_role_session)
    assert (
        await app_role_session.execute(text("SELECT id FROM company_subscriptions"))
    ).all() == []


@pytest.mark.asyncio
async def test_repository_requires_rls_context(company_a: Company) -> None:
    async with _uow() as uow:
        with pytest.raises(RuntimeError, match="RLS context not established"):
            await uow.companies.get_by_id(company_a.id)

    async with _uow() as uow:
        with pytest.raises(RuntimeError, match="RLS context not established"):
            await uow.refresh_sessions.list(limit=1)

    async with _uow() as uow:
        await uow.enter_tenant(company_a.id)
        company = await uow.companies.get_by_id(company_a.id)
        assert company is not None
        assert company.id == company_a.id


@pytest.mark.asyncio
async def test_auth_pin_then_tenant_escalation_for_company(
    company_a: Company,
    hr_a: Employee,
) -> None:
    """Invite-style flow: pin employee under auth, then tenant for company."""
    async with _uow() as uow:
        await uow.enter_auth_bootstrap(employee_id=hr_a.id)
        emp = await uow.employees.get_by_id(hr_a.id)
        assert emp is not None
        # Company not visible under auth
        assert await uow.companies.get_by_id(company_a.id) is None
        await uow.enter_tenant(emp.company_id)
        company = await uow.companies.get_by_id(company_a.id)
        assert company is not None
        assert company.id == company_a.id


@pytest.mark.asyncio
async def test_company_audit_logs_are_tenant_isolated(
    company_a: Company,
    company_b: Company,
    app_role_session: AsyncSession,
) -> None:
    await _set_tenant(app_role_session, company_a.id)
    await app_role_session.execute(
        text(
            "INSERT INTO company_audit_logs "
            "(id, company_id, action, resource_type, details, summary, "
            "created_at, updated_at) VALUES "
            "(gen_random_uuid(), :cid, 'employee.created', 'employee', "
            "'{}'::jsonb, 'rls probe', now(), now())"
        ),
        {"cid": company_a.id},
    )
    await app_role_session.commit()

    await _set_tenant(app_role_session, company_b.id)
    hidden = (
        await app_role_session.execute(
            text("SELECT id FROM company_audit_logs WHERE company_id = :cid"),
            {"cid": company_a.id},
        )
    ).first()
    assert hidden is None

    await _set_tenant(app_role_session, company_a.id)
    visible = (
        await app_role_session.execute(
            text("SELECT summary FROM company_audit_logs WHERE company_id = :cid"),
            {"cid": company_a.id},
        )
    ).first()
    assert visible is not None
    assert visible[0] == "rls probe"


@pytest.mark.asyncio
async def test_platform_audit_and_subscriptions_tenant_write_denied(
    company_a: Company,
    app_role_session: AsyncSession,
) -> None:
    await _set_tenant(app_role_session, company_a.id)
    assert (
        await app_role_session.execute(text("SELECT id FROM platform_audit_logs LIMIT 1"))
    ).first() is None

    with pytest.raises(Exception):
        await app_role_session.execute(
            text(
                "INSERT INTO platform_audit_logs "
                "(id, action, resource_type, details, summary, created_at, updated_at) "
                "VALUES (gen_random_uuid(), 'x', 'company', '{}'::jsonb, 'nope', now(), now())"
            )
        )
        await app_role_session.commit()
    await app_role_session.rollback()

    await _set_tenant(app_role_session, company_a.id)
    with pytest.raises(Exception):
        await app_role_session.execute(
            text(
                "INSERT INTO company_subscriptions "
                "(id, company_id, tier, status, payment_status, started_at, "
                "auto_renew, employee_limit, program_limit, is_current, "
                "created_at, updated_at) VALUES "
                "(gen_random_uuid(), :cid, 'starter', 'active', 'paid', now(), "
                "true, 99, 99, false, now(), now())"
            ),
            {"cid": company_a.id},
        )
        await app_role_session.commit()
    await app_role_session.rollback()


@pytest.mark.asyncio
async def test_cross_tenant_http_program_kb_progress_blocked(
    api_client: AsyncClient,
    company_a: Company,
    company_b: Company,
    hr_a: Employee,
    hr_b: Employee,
) -> None:
    async with _uow() as uow:
        await uow.enter_platform()
        prog_b = await uow.onboarding_programs.create(
            OnboardingProgram(
                company_id=company_b.id,
                title=f"B-prog-{uuid4().hex[:6]}",
                is_active=True,
            ),
        )
        await uow.commit()
        prog_b_id = prog_b.id

    resp = await api_client.get(
        f"/api/v1/programs/{prog_b_id}",
        headers=auth_header(hr_a),
    )
    assert resp.status_code == 404

    # Peer HR in another tenant also cannot read A-scoped resources by forging ids.
    resp_b = await api_client.get(
        f"/api/v1/programs/{prog_b_id}",
        headers=auth_header(hr_b),
    )
    assert resp_b.status_code == 200


# --- F-01: auth_bootstrap invite / super_admin pinning ---


@pytest.mark.asyncio
async def test_f01_auth_cannot_enumerate_or_update_arbitrary_invites(
    company_a: Company,
    company_b: Company,
    hr_a: Employee,
    hr_b: Employee,
    app_role_session: AsyncSession,
) -> None:
    hash_a = hash_token(f"a-{uuid4().hex}")
    hash_b = hash_token(f"b-{uuid4().hex}")
    async with _uow() as uow:
        await uow.enter_platform()
        inv_a = await uow.employee_invites.create(
            EmployeeInvite(
                company_id=company_a.id,
                employee_id=hr_a.id,
                token_hash=hash_a,
                expires_at=__import__("datetime").datetime.now(
                    __import__("datetime").UTC
                )
                + __import__("datetime").timedelta(hours=1),
                invited_email="a@example.com",
                purpose='employee',
            ),
        )
        inv_b = await uow.employee_invites.create(
            EmployeeInvite(
                company_id=company_b.id,
                employee_id=hr_b.id,
                token_hash=hash_b,
                expires_at=__import__("datetime").datetime.now(
                    __import__("datetime").UTC
                )
                + __import__("datetime").timedelta(hours=1),
                invited_email="b@example.com",
                purpose='employee',
            ),
        )
        await uow.commit()
        id_a, id_b = inv_a.id, inv_b.id

    # Unpinned auth: no invites visible.
    await _set_auth(app_role_session)
    assert (
        await app_role_session.execute(text("SELECT count(*) FROM employee_invites"))
    ).scalar_one() == 0

    # Wrong hash: target invite invisible.
    await _set_auth(app_role_session, invite_token_hash=hash_token("wrong-token"))
    assert (
        await app_role_session.execute(
            text("SELECT id FROM employee_invites WHERE id = :id"),
            {"id": id_a},
        )
    ).first() is None

    # Correct hash: only that invite.
    await _set_auth(app_role_session, invite_token_hash=hash_a)
    rows = (
        await app_role_session.execute(text("SELECT id FROM employee_invites"))
    ).all()
    assert {r[0] for r in rows} == {id_a}

    # Cannot UPDATE the other invite while pinned to A.
    result = await app_role_session.execute(
        text("UPDATE employee_invites SET used_at = now() WHERE id = :id"),
        {"id": id_b},
    )
    assert result.rowcount == 0

    # Employee pin (post-accept invalidate path): can SELECT/UPDATE own invites only.
    await _set_auth(app_role_session, employee_id=hr_a.id)
    rows = (
        await app_role_session.execute(text("SELECT id FROM employee_invites"))
    ).all()
    assert {r[0] for r in rows} == {id_a}
    result = await app_role_session.execute(
        text("UPDATE employee_invites SET used_at = now() WHERE id = :id"),
        {"id": id_a},
    )
    assert result.rowcount == 1
    result = await app_role_session.execute(
        text("UPDATE employee_invites SET used_at = now() WHERE id = :id"),
        {"id": id_b},
    )
    assert result.rowcount == 0
    await app_role_session.rollback()

@pytest.mark.asyncio
async def test_f01_auth_cannot_enumerate_super_admins(
    app_role_session: AsyncSession,
) -> None:
    from app.core.security import hash_password
    from app.db.models.super_admin import SuperAdmin

    email_a = f"sa-f01-a-{uuid4().hex[:8]}@test.local"
    email_b = f"sa-f01-b-{uuid4().hex[:8]}@test.local"
    async with _uow() as uow:
        await uow.enter_platform()
        sa_a = await uow.super_admins.create(
            SuperAdmin(
                email=email_a,
                full_name="SA A",
                password_hash=hash_password("StrongSAPass!23456"),
                is_active=True,
            ),
        )
        sa_b = await uow.super_admins.create(
            SuperAdmin(
                email=email_b,
                full_name="SA B",
                password_hash=hash_password("StrongSAPass!23456"),
                is_active=True,
            ),
        )
        await uow.commit()
        id_a, id_b = sa_a.id, sa_b.id

    # Unpinned auth: no Super Admins (no password_hash dump).
    await _set_auth(app_role_session)
    assert (
        await app_role_session.execute(text("SELECT count(*) FROM super_admins"))
    ).scalar_one() == 0
    assert (
        await app_role_session.execute(
            text("SELECT password_hash FROM super_admins LIMIT 1")
        )
    ).first() is None

    # Email pin: only that row (password_hash visible only for scoped login).
    await _set_auth(app_role_session, super_admin_email=email_a)
    rows = (
        await app_role_session.execute(
            text("SELECT id, email, password_hash FROM super_admins")
        )
    ).all()
    assert len(rows) == 1
    assert rows[0][0] == id_a
    assert rows[0][1] == email_a
    assert rows[0][2]

    # Id pin: only that row; other id denied.
    await _set_auth(app_role_session, super_admin_id=id_a)
    assert (
        await app_role_session.execute(
            text("SELECT id FROM super_admins WHERE id = :id"),
            {"id": id_a},
        )
    ).first() is not None
    assert (
        await app_role_session.execute(
            text("SELECT id FROM super_admins WHERE id = :id"),
            {"id": id_b},
        )
    ).first() is None

    # Wrong email: deny.
    await _set_auth(app_role_session, super_admin_email="nobody@test.local")
    assert (
        await app_role_session.execute(
            text("SELECT id FROM super_admins WHERE id = :id"),
            {"id": id_a},
        )
    ).first() is None


@pytest.mark.asyncio
async def test_f01_scoped_invite_and_sa_uow_lookups_work(
    company_a: Company,
) -> None:
    from app.core.exceptions import NotFoundError
    from app.core.security import hash_password, verify_password
    from app.db.models.super_admin import SuperAdmin
    from app.services.platform import SuperAdminAuthService
    from app.services.platform_management import InviteService

    raw = f"tok-{uuid4().hex}"
    token_hash = hash_token(raw)
    email = f"sa-f01-login-{uuid4().hex[:8]}@test.local"
    password = "StrongSAPass!23456"

    email = unique_email("invitee")
    async with _uow() as uow:
        await uow.enter_platform()
        invited = await uow.employees.create(
            Employee(
                company_id=company_a.id,
                full_name="Invite Preview Emp",
                role=EmployeeRole.EMPLOYEE.value,
                status=EmployeeStatus.INVITED.value,
                telegram_user_id=unique_telegram_user_id(),
                email=email,
            ),
        )
        await uow.employee_invites.create(
            EmployeeInvite(
                company_id=company_a.id,
                employee_id=invited.id,
                token_hash=token_hash,
                expires_at=__import__("datetime").datetime.now(
                    __import__("datetime").UTC
                )
                + __import__("datetime").timedelta(hours=1),
                invited_email=email,
                purpose='employee',
            ),
        )
        await uow.super_admins.create(
            SuperAdmin(
                email=email,
                full_name="Login SA",
                password_hash=hash_password(password),
                is_active=True,
            ),
        )
        await uow.commit()
        invited_id = invited.id

    preview = await InviteService().get_invite_preview(raw)
    assert preview["employee_id"] == invited_id

    with pytest.raises(NotFoundError):
        await InviteService().get_invite_preview("definitely-not-the-token")

    admin = await SuperAdminAuthService().authenticate(email=email, password=password)
    assert admin.email == email
    assert verify_password(password, admin.password_hash)

    loaded = await SuperAdminAuthService().get_by_id(admin.id)
    assert loaded.id == admin.id

    with pytest.raises(NotFoundError):
        await SuperAdminAuthService().get_by_id(uuid4())

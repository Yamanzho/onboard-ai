"""FORCE RLS for assignment_reminder_preferences."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import get_settings
from app.db.models.assignment import Assignment
from app.db.models.assignment_reminder_preference import AssignmentReminderPreference
from app.db.models.company import Company
from app.db.models.employee import Employee
from app.db.models.onboarding_program import OnboardingProgram
from tests.conftest import _uow_factory
from tests.security.test_rls_adversarial import _set_tenant

pytestmark = pytest.mark.security

_TABLE = "assignment_reminder_preferences"


@pytest.fixture
async def app_role_session() -> AsyncSession:
    settings = get_settings()
    url = settings.database_url
    if "onboard_app" not in url and "onboard_owner" in url:
        url = url.replace("onboard_owner", "onboard_app")
    engine = create_async_engine(url, echo=False, connect_args={"ssl": False})
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        yield session
    await engine.dispose()


@pytest.mark.asyncio
async def test_reminder_preferences_force_rls_and_grants(
    app_role_session: AsyncSession,
) -> None:
    row = (
        await app_role_session.execute(
            text(
                "SELECT relrowsecurity, relforcerowsecurity FROM pg_class "
                "WHERE relname = :table"
            ),
            {"table": _TABLE},
        )
    ).one()
    assert row[0] is True
    assert row[1] is True
    granted = (
        await app_role_session.execute(
            text(
                """
                SELECT has_table_privilege('onboard_app', :table, 'INSERT')
                AND has_table_privilege('onboard_app', :table, 'SELECT')
                AND has_table_privilege('onboard_app', :table, 'UPDATE')
                AND has_table_privilege('onboard_app', :table, 'DELETE')
                """
            ),
            {"table": _TABLE},
        )
    ).scalar_one()
    assert granted is True


@pytest.mark.asyncio
async def test_tenant_cannot_read_other_tenant_reminder_prefs(
    app_role_session: AsyncSession,
    company_a: Company,
    company_b: Company,
    employee_a: Employee,
) -> None:
    async with _uow_factory() as uow:
        await uow.enter_tenant(company_a.id)
        program = await uow.onboarding_programs.create(
            OnboardingProgram(
                company_id=company_a.id,
                title="RLS Course",
                is_active=True,
            )
        )
        assignment = await uow.assignments.create(
            Assignment(
                company_id=company_a.id,
                employee_id=employee_a.id,
                program_id=program.id,
                status="pending",
                assigned_at=datetime.now(UTC),
            )
        )
        pref = await uow.assignment_reminders.create(
            AssignmentReminderPreference(
                company_id=company_a.id,
                assignment_id=assignment.id,
                employee_id=employee_a.id,
                mode="default",
            )
        )
        pref_id = pref.id
        await uow.commit()

    await _set_tenant(app_role_session, company_b.id)
    visible = (
        await app_role_session.execute(
            text(f"SELECT count(*) FROM {_TABLE} WHERE id = :id"),
            {"id": pref_id},
        )
    ).scalar_one()
    mutated = await app_role_session.execute(
        text(f"UPDATE {_TABLE} SET mode = 'disabled' WHERE id = :id"),
        {"id": pref_id},
    )
    assert visible == 0
    assert mutated.rowcount == 0
    await app_role_session.rollback()

"""FORCE RLS isolation for departments, question_topics, topic_responsibilities."""

from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import get_settings
from app.db.models.company import Company
from app.db.models.department import Department
from app.db.models.question_topic import QuestionTopic
from app.db.models.topic_responsibility import TopicResponsibility
from tests.conftest import _uow_factory
from tests.security.test_rls_adversarial import _set_tenant

pytestmark = pytest.mark.security


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


_TABLES = ("departments", "question_topics", "topic_responsibilities")


@pytest.mark.asyncio
async def test_organization_tables_force_rls_enabled(
    app_role_session: AsyncSession,
) -> None:
    for table in _TABLES:
        row = (
            await app_role_session.execute(
                text(
                    "SELECT relrowsecurity, relforcerowsecurity FROM pg_class "
                    "WHERE relname = :table"
                ),
                {"table": table},
            )
        ).one()
        assert row[0] is True, table
        assert row[1] is True, table


@pytest.mark.asyncio
async def test_onboard_app_is_granted_dml_on_organization_tables(
    app_role_session: AsyncSession,
) -> None:
    for table in _TABLES:
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
                {"table": table},
            )
        ).scalar_one()
        assert granted is True, table


@pytest.mark.asyncio
async def test_tenant_cannot_select_other_tenant_organization_rows(
    company_a: Company,
    company_b: Company,
    app_role_session: AsyncSession,
) -> None:
    async with _uow_factory() as uow:
        await uow.enter_platform()
        department = await uow.departments.create(
            Department(
                company_id=company_a.id,
                name="HR",
                slug=f"hr-{uuid4().hex[:8]}",
            ),
        )
        topic = await uow.question_topics.create(
            QuestionTopic(
                company_id=company_a.id,
                name="Vacation",
                slug=f"vacation-{uuid4().hex[:8]}",
            ),
        )
        mapping = await uow.topic_responsibilities.create(
            TopicResponsibility(
                company_id=company_a.id,
                topic_id=topic.id,
                department_id=department.id,
            ),
        )
        await uow.commit()

    await _set_tenant(app_role_session, company_b.id)
    dept_count = (
        await app_role_session.execute(
            text("SELECT count(*) FROM departments WHERE id = :id"),
            {"id": department.id},
        )
    ).scalar_one()
    topic_count = (
        await app_role_session.execute(
            text("SELECT count(*) FROM question_topics WHERE id = :id"),
            {"id": topic.id},
        )
    ).scalar_one()
    mapping_count = (
        await app_role_session.execute(
            text("SELECT count(*) FROM topic_responsibilities WHERE id = :id"),
            {"id": mapping.id},
        )
    ).scalar_one()
    assert dept_count == 0
    assert topic_count == 0
    assert mapping_count == 0
    await app_role_session.rollback()

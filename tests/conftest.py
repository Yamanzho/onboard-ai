"""Shared fixtures for knowledge service/API tests against live Postgres."""

from __future__ import annotations

from collections.abc import AsyncIterator
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.db.session as db_session
from app.api import deps as api_deps
from app.core.config import get_settings
from app.core.security import create_access_token
from app.db.enums import EmployeeRole, EmployeeStatus
from app.db.models.company import Company
from app.db.models.employee import Employee
from app.db.uow import UnitOfWork
from app.main import app
from app.services.knowledge.article_service import ArticleService
from app.services.knowledge.category_service import CategoryService
from app.services.knowledge.tag_service import TagService


@pytest.fixture(scope="session", autouse=True)
async def _bind_engine_to_session_loop() -> AsyncIterator[None]:
    """Recreate the global async engine on pytest-asyncio's session loop.

    Import-time engines are bound to a different loop and can segfault/asyncpg-fail
    when pytest creates a fresh loop per test/session.
    """
    settings = get_settings()
    await db_session.engine.dispose()
    engine = create_async_engine(
        settings.database_url,
        echo=False,
        connect_args={"ssl": False},
    )
    factory: async_sessionmaker[AsyncSession] = async_sessionmaker(
        engine,
        expire_on_commit=False,
    )
    db_session.engine = engine
    db_session.async_session_factory = factory

    # Clear cached service singletons so they pick up the rebound session factory.
    api_deps.get_article_service.cache_clear()
    api_deps.get_category_service.cache_clear()
    api_deps.get_tag_service.cache_clear()
    api_deps.get_employee_service.cache_clear()
    api_deps.get_company_service.cache_clear()

    try:
        yield
    finally:
        await engine.dispose()


def _uow_factory() -> UnitOfWork:
    return UnitOfWork(session_factory=db_session.async_session_factory)


async def _create_company(*, name: str | None = None) -> Company:
    suffix = uuid4().hex[:10]
    async with _uow_factory() as uow:
        company = await uow.companies.create(
            Company(
                name=name or f"Test Co {suffix}",
                slug=f"test-{suffix}",
                timezone="UTC",
                is_active=True,
                settings={},
            ),
        )
        await uow.commit()
        return company


async def _create_employee(
    *,
    company_id,
    role: str = EmployeeRole.HR.value,
) -> Employee:
    suffix = uuid4().int % 1_000_000_000
    async with _uow_factory() as uow:
        employee = await uow.employees.create(
            Employee(
                company_id=company_id,
                telegram_user_id=suffix + 1,
                full_name=f"Test {role}",
                role=role,
                status=EmployeeStatus.ACTIVE.value,
            ),
        )
        await uow.commit()
        return employee


async def _delete_company(company_id) -> None:
    async with _uow_factory() as uow:
        await uow.companies.delete(company_id)
        await uow.commit()


@pytest.fixture
async def company_a() -> AsyncIterator[Company]:
    company = await _create_company(name="Company A")
    try:
        yield company
    finally:
        await _delete_company(company.id)


@pytest.fixture
async def company_b() -> AsyncIterator[Company]:
    company = await _create_company(name="Company B")
    try:
        yield company
    finally:
        await _delete_company(company.id)


@pytest.fixture
async def hr_a(company_a: Company) -> Employee:
    return await _create_employee(company_id=company_a.id, role=EmployeeRole.HR.value)


@pytest.fixture
async def hr_b(company_b: Company) -> Employee:
    return await _create_employee(company_id=company_b.id, role=EmployeeRole.HR.value)


@pytest.fixture
def article_service() -> ArticleService:
    return ArticleService(uow_factory=_uow_factory)


@pytest.fixture
def category_service() -> CategoryService:
    return CategoryService(uow_factory=_uow_factory)


@pytest.fixture
def tag_service() -> TagService:
    return TagService(uow_factory=_uow_factory)


@pytest.fixture
async def api_client() -> AsyncIterator[AsyncClient]:
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


def auth_header(employee: Employee) -> dict[str, str]:
    token = create_access_token(
        subject=employee.id,
        role=employee.role,
        company_id=employee.company_id,
    )
    return {"Authorization": f"Bearer {token}"}

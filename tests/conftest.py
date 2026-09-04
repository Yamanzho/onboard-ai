"""Shared fixtures for knowledge service/API tests against live Postgres."""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path
from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

import app.db.session as db_session
from app.api import deps as api_deps
from app.core.ai_constants import KB_CHUNK_VECTOR_DIMENSION
from app.core.auth_cookies import (
    ACCESS_COOKIE,
    REFRESH_COOKIE,
    SA_ACCESS_COOKIE,
    SA_REFRESH_COOKIE,
)
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


@pytest.fixture(autouse=True)
def _lifecycle_ready_for_tests() -> None:
    """HTTP tests assume a ready process; drain tests reset this explicitly."""
    from app.core.lifecycle import mark_ready, reset_lifecycle_for_tests

    reset_lifecycle_for_tests()
    mark_ready()
    yield
    reset_lifecycle_for_tests()


@pytest.fixture(autouse=True)
def telegram_conversation_store():
    """Keep Telegram conversation pointers off live Redis during tests."""
    import app.bot.services.ai_conversation as store_mod
    from app.bot.services.ai_conversation import (
        MemoryRedisClient,
        TelegramConversationStore,
        reset_telegram_conversation_store_for_tests,
    )

    store = TelegramConversationStore(redis_client=MemoryRedisClient())
    store_mod._store = store
    yield store
    reset_telegram_conversation_store_for_tests()


@pytest.fixture(scope="session", autouse=True)
async def _bind_engine_to_session_loop() -> AsyncIterator[None]:
    """Recreate the global async engine on pytest-asyncio's session loop.

    Import-time engines are bound to a different loop and can segfault/asyncpg-fail
    when pytest creates a fresh loop per test/session.
    """
    settings = get_settings()
    # Disable auth rate limits in tests (shared client IP would otherwise 429).
    settings.login_rate_limit = 0
    settings.bot_login_rate_limit = 0
    settings.invite_preview_rate_limit = 0
    settings.invite_accept_rate_limit = 0
    settings.refresh_rate_limit = 0
    settings.ai_chat_rate_limit = 0
    settings.ai_embedding_provider = "fake"
    settings.ai_embedding_dimension = KB_CHUNK_VECTOR_DIMENSION
    settings.ai_llm_provider = "fake"

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
    api_deps.get_chunk_indexer.cache_clear()
    api_deps.get_ai_chat_service.cache_clear()
    api_deps.get_category_service.cache_clear()
    api_deps.get_tag_service.cache_clear()
    api_deps.get_employee_service.cache_clear()
    api_deps.get_department_service.cache_clear()
    api_deps.get_question_topic_service.cache_clear()
    api_deps.get_responsibility_lookup_service.cache_clear()
    api_deps.get_company_service.cache_clear()
    api_deps.get_super_admin_auth_service.cache_clear()
    api_deps.get_platform_service.cache_clear()

    try:
        yield
    finally:
        await engine.dispose()


@pytest.fixture(autouse=True)
def _keep_auth_rate_limits_disabled() -> None:
    """Re-apply after any test that calls ``get_settings.cache_clear()``.

    Cached Settings recreation restores default login limits (10/min), which
    causes flaky 429s across the shared test client IP.
    """
    settings = get_settings()
    settings.login_rate_limit = 0
    settings.bot_login_rate_limit = 0
    settings.invite_preview_rate_limit = 0
    settings.invite_accept_rate_limit = 0
    settings.refresh_rate_limit = 0
    settings.ai_chat_rate_limit = 0
    settings.ai_embedding_provider = "fake"
    settings.ai_embedding_dimension = KB_CHUNK_VECTOR_DIMENSION
    settings.ai_llm_provider = "fake"


def _uow_factory() -> UnitOfWork:
    return UnitOfWork(session_factory=db_session.async_session_factory)


async def _create_company(*, name: str | None = None) -> Company:
    suffix = uuid4().hex[:10]
    async with _uow_factory() as uow:
        await uow.enter_platform()
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
        await uow.enter_platform()
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
        await uow.enter_platform()
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
async def admin_a(company_a: Company) -> Employee:
    return await _create_employee(company_id=company_a.id, role=EmployeeRole.ADMIN.value)


@pytest.fixture
async def employee_a(company_a: Company) -> Employee:
    return await _create_employee(
        company_id=company_a.id,
        role=EmployeeRole.EMPLOYEE.value,
    )


@pytest.fixture
async def admin_b(company_b: Company) -> Employee:
    return await _create_employee(company_id=company_b.id, role=EmployeeRole.ADMIN.value)


@pytest.fixture
async def employee_b(company_b: Company) -> Employee:
    return await _create_employee(
        company_id=company_b.id,
        role=EmployeeRole.EMPLOYEE.value,
    )


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


def tenant_tokens_from_response(response) -> dict[str, str]:
    """Read access/refresh from Set-Cookie after cookie-only browser login."""
    access = response.cookies.get(ACCESS_COOKIE)
    refresh = response.cookies.get(REFRESH_COOKIE)
    assert access, "expected onboard_access cookie"
    assert refresh, "expected onboard_refresh cookie"
    return {"access_token": access, "refresh_token": refresh}


def sa_tokens_from_response(response) -> dict[str, str]:
    """Read Super Admin access/refresh from Set-Cookie after cookie-only login."""
    access = response.cookies.get(SA_ACCESS_COOKIE)
    refresh = response.cookies.get(SA_REFRESH_COOKIE)
    assert access, "expected onboard_sa_access cookie"
    assert refresh, "expected onboard_sa_refresh cookie"
    return {"access_token": access, "refresh_token": refresh}


_SECURITY_PATH_HINTS = (
    "/tests/security/",
    "pentest",
    "_acl",
    "peer_hr_authz",
    "telegram_invite",
    "invite_active_takeover",
    "subscription_entitlement",
    "public_gate",
    "session_hardening",
    "cookie_auth",
    "tenant_isolation",
    "security_hardening",
    "trust_proxy",
    "production_secrets",
    "rate_limit_production",
    "ai_chat",
    "rls",
)

_TELEGRAM_PATH_HINTS = (
    "/tests/bot/",
    "telegram",
    "bot_login",
    "redis_storage",
)


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Auto-mark tests from path so CI can filter the matrix without touching every file."""
    for item in items:
        path = Path(str(item.path)).as_posix()
        lowered = path.lower()
        if "/tests/api/" in path:
            item.add_marker(pytest.mark.api)
        if "/tests/core/" in path or "/tests/knowledge/" in path or "/tests/ai/" in path:
            item.add_marker(pytest.mark.unit)
        if "/tests/e2e/" in path:
            item.add_marker(pytest.mark.integration)
        if "/tests/infra/" in path:
            item.add_marker(pytest.mark.infra)
        if any(hint in lowered for hint in _SECURITY_PATH_HINTS):
            item.add_marker(pytest.mark.security)
        if any(hint in lowered for hint in _TELEGRAM_PATH_HINTS):
            item.add_marker(pytest.mark.telegram)


"""OpenAPI / Swagger / ReDoc availability by APP_ENV (P0-05)."""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from app.core.config import Settings
from app.main import app, create_app


def _production_settings(**overrides: object) -> Settings:
    """Build production Settings without reading the project ``.env`` file."""
    base: dict[str, object] = {
        "_env_file": None,
        "app_env": "production",
        "debug": False,
        "secret_key": "unit-test-hmac-secret-key-32chars-min!!",
        "super_admin_password": "unit-test-super-admin-ok",
        "bot_service_token": "unit-test-bot-service-token-32chars",
        "redis_url": "redis://:unit-test-redis-password@redis:6379/0",
        "database_url": (
            "postgresql+asyncpg://onboard_app:unit-test-postgres-password@db:5432/onboard_ai"
        ),
        "migration_database_url": (
            "postgresql+asyncpg://onboard_owner:unit-test-postgres-password@db:5432/onboard_ai"
        ),
        "onboard_owner_password": "unit-test-postgres-password",
        "onboard_app_password": "unit-test-postgres-password",
        "invite_base_url": "https://onboardai.example.test",
        "ai_allow_fake_embeddings_in_production": True,
        "ai_allow_fake_llm_in_production": True,
    }
    base.update(overrides)
    return Settings(**base)  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_development_docs_endpoints_available() -> None:
    """Default app (development) exposes Swagger / OpenAPI / ReDoc."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        docs = await client.get("/docs")
        openapi = await client.get("/openapi.json")
        redoc = await client.get("/redoc")
        health = await client.get("/health")

    assert docs.status_code == 200
    assert openapi.status_code == 200
    assert "openapi" in openapi.json()
    assert redoc.status_code == 200
    assert health.status_code == 200
    assert health.json() == {"status": "ok"}


@pytest.mark.asyncio
async def test_production_docs_endpoints_return_404() -> None:
    """Production app disables docs_url / redoc_url / openapi_url."""
    prod_app = create_app(_production_settings())
    transport = ASGITransport(app=prod_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        docs = await client.get("/docs")
        openapi = await client.get("/openapi.json")
        redoc = await client.get("/redoc")
        health = await client.get("/health")

    assert docs.status_code == 404
    assert openapi.status_code == 404
    assert redoc.status_code == 404
    assert health.status_code == 200
    assert health.json() == {"status": "ok"}


@pytest.mark.asyncio
async def test_production_api_routes_still_registered() -> None:
    """Disabling OpenAPI must not remove the API router."""
    prod_app = create_app(_production_settings())
    assert prod_app.openapi_url is None
    assert prod_app.docs_url is None
    assert prod_app.redoc_url is None

    transport = ASGITransport(app=prod_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        health = await client.get("/health")
        # Auth-required route must still exist (401 without credentials).
        me = await client.get("/api/v1/auth/me")

    assert health.status_code == 200
    assert me.status_code == 401


@pytest.mark.asyncio
async def test_development_create_app_keeps_docs() -> None:
    settings = Settings(_env_file=None, app_env="development", debug=True)
    dev_app = create_app(settings)
    assert dev_app.docs_url == "/docs"
    assert dev_app.redoc_url == "/redoc"
    assert dev_app.openapi_url == "/openapi.json"

    transport = ASGITransport(app=dev_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        assert (await client.get("/docs")).status_code == 200
        assert (await client.get("/openapi.json")).status_code == 200
        assert (await client.get("/redoc")).status_code == 200

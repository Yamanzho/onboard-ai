"""Liveness ``/health`` vs readiness ``/ready``."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr

from app.core.config import Settings, get_settings
from app.core.exceptions import ServiceUnavailableError
from app.core.readiness import check_redis_if_required
from app.main import create_app
from tests.api.test_openapi_docs import _production_settings


def _assert_no_connection_leak(body: str) -> None:
    lowered = body.lower()
    for needle in (
        "postgresql",
        "redis://",
        "password",
        "localhost",
        "5432",
        "6379",
        "onboard_app",
        "onboard_owner",
    ):
        assert needle not in lowered, f"readiness body leaked {needle!r}: {body}"


@pytest.mark.asyncio
async def test_health_is_liveness_without_dependencies(api_client) -> None:
    response = await api_client.get("/health")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    _assert_no_connection_leak(response.text)


@pytest.mark.asyncio
async def test_ready_ok_when_database_is_up(api_client) -> None:
    response = await api_client.get("/ready")
    assert response.status_code == 200, response.text
    assert response.json() == {"status": "ready"}
    _assert_no_connection_leak(response.text)


@pytest.mark.asyncio
async def test_ready_503_when_database_unavailable(api_client, monkeypatch) -> None:
    async def _fail() -> None:
        raise ServiceUnavailableError("database unavailable")

    monkeypatch.setattr("app.core.readiness.check_database", _fail)
    response = await api_client.get("/ready")
    assert response.status_code == 503
    assert response.json()["detail"] == "database unavailable"
    _assert_no_connection_leak(response.text)
    # Liveness must not follow dependency failure.
    health = await api_client.get("/health")
    assert health.status_code == 200
    assert health.json() == {"status": "ok"}


@pytest.mark.asyncio
async def test_production_app_registers_health_and_ready() -> None:
    prod_app = create_app(_production_settings())
    paths = {getattr(route, "path", None) for route in prod_app.routes}
    assert "/health" in paths
    assert "/ready" in paths
    transport = ASGITransport(app=prod_app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        health = await client.get("/health")
    assert health.status_code == 200
    assert health.json() == {"status": "ok"}


@pytest.mark.asyncio
async def test_production_ready_503_when_redis_down(
    api_client,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = _production_settings()
    monkeypatch.setattr("app.core.readiness.get_settings", lambda: settings)
    with patch("redis.Redis.from_url", side_effect=ConnectionError("down")):
        response = await api_client.get("/ready")
    assert response.status_code == 503
    assert response.json()["detail"] == "redis unavailable"
    _assert_no_connection_leak(response.text)
    health = await api_client.get("/health")
    assert health.status_code == 200


def test_redis_check_skipped_outside_production(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = get_settings()
    monkeypatch.setattr(settings, "app_env", "development")
    with patch("redis.Redis.from_url") as from_url:
        check_redis_if_required()
    from_url.assert_not_called()


def test_redis_check_required_in_production_success(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = _production_settings()
    monkeypatch.setattr("app.core.readiness.get_settings", lambda: settings)
    client = MagicMock()
    with patch("redis.Redis.from_url", return_value=client) as from_url:
        check_redis_if_required()
    from_url.assert_called_once()
    client.ping.assert_called_once()
    client.close.assert_called_once()


def test_redis_check_required_in_production_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = _production_settings()
    monkeypatch.setattr("app.core.readiness.get_settings", lambda: settings)
    with patch("redis.Redis.from_url", side_effect=ConnectionError("boom")):
        with pytest.raises(ServiceUnavailableError, match="redis unavailable"):
            check_redis_if_required()


def test_production_settings_helper_is_settings() -> None:
    assert isinstance(_production_settings(), Settings)


def test_ready_ai_config_does_not_call_openai(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core.readiness import check_ai_config

    with patch("httpx.AsyncClient") as client_cls:
        check_ai_config()
    client_cls.assert_not_called()


@pytest.mark.asyncio
async def test_ready_503_while_draining_health_stays_ok(api_client) -> None:
    from app.core.lifecycle import begin_drain, mark_ready

    mark_ready()
    begin_drain()
    response = await api_client.get("/ready")
    assert response.status_code == 503
    assert response.json()["detail"] == "draining"
    _assert_no_connection_leak(response.text)
    health = await api_client.get("/health")
    assert health.status_code == 200
    assert health.json() == {"status": "ok"}


@pytest.mark.asyncio
async def test_ready_503_while_starting(api_client) -> None:
    from app.core.lifecycle import reset_lifecycle_for_tests

    reset_lifecycle_for_tests()
    response = await api_client.get("/ready")
    assert response.status_code == 503
    assert response.json()["detail"] == "not ready"
    _assert_no_connection_leak(response.text)


def test_ready_ai_config_fails_closed_without_openai_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.core.readiness import check_ai_config

    settings = get_settings()
    monkeypatch.setattr(settings, "ai_llm_provider", "openai")
    monkeypatch.setattr(settings, "ai_llm_api_key", SecretStr(""))
    with patch("httpx.AsyncClient") as client_cls:
        with pytest.raises(ServiceUnavailableError, match="ai llm not configured"):
            check_ai_config()
    client_cls.assert_not_called()

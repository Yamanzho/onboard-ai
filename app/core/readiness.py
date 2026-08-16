"""Liveness vs readiness probes.

``/health`` is process liveness and does not touch dependencies.
``/ready`` checks PostgreSQL always, and Redis when it is a required runtime
dependency (``APP_ENV=production``).

Error messages never include URLs, hosts, passwords, or other connection details.
"""

from __future__ import annotations

from sqlalchemy import text

from app.core.config import get_settings
from app.core.exceptions import ServiceUnavailableError


async def check_database() -> None:
    """Fail closed if PostgreSQL is not reachable."""
    from app.db import session as db_session

    try:
        async with db_session.engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
    except Exception:
        raise ServiceUnavailableError("database unavailable") from None


def check_redis_if_required() -> None:
    """Fail closed on Redis only when production requires it."""
    settings = get_settings()
    if not settings.is_production:
        return
    try:
        from redis import Redis

        client = Redis.from_url(
            settings.redis_url,
            socket_connect_timeout=2,
            socket_timeout=2,
        )
        try:
            client.ping()
        finally:
            client.close()
    except ServiceUnavailableError:
        raise
    except Exception:
        raise ServiceUnavailableError("redis unavailable") from None


async def assert_ready() -> None:
    """Raise ``ServiceUnavailableError`` when the app must not receive traffic."""
    await check_database()
    check_redis_if_required()
    check_ai_config()


def check_ai_config() -> None:
    """Fail closed when hosted AI is selected without a key. Never calls OpenAI."""
    settings = get_settings()
    if settings.ai_embedding_provider == "openai":
        if not settings.ai_embedding_api_key.get_secret_value().strip():
            raise ServiceUnavailableError("ai embedding not configured")
    if settings.ai_llm_provider == "openai":
        if not settings.ai_llm_api_key.get_secret_value().strip():
            raise ServiceUnavailableError("ai llm not configured")

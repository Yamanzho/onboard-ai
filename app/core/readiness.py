"""Liveness vs readiness probes.

``/health`` is process liveness and does not touch dependencies.
``/ready`` is false while the process is starting, draining, or stopped.
When the process is ready it checks PostgreSQL always, and Redis when it is a
required runtime dependency (``APP_ENV=production``).

Error messages never include URLs, hosts, passwords, or other connection details.
"""

from __future__ import annotations

import time

from sqlalchemy import text

from app.core.config import get_settings
from app.core.exceptions import ServiceUnavailableError
from app.core.lifecycle import ProcessState, current_state, is_accepting_traffic
from app.core.metrics import READINESS, record_dependency


async def check_database() -> None:
    """Fail closed if PostgreSQL is not reachable."""
    from app.db import session as db_session

    started = time.perf_counter()
    try:
        async with db_session.engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
    except Exception:
        record_dependency(
            "postgres",
            up=False,
            duration_seconds=time.perf_counter() - started,
        )
        raise ServiceUnavailableError("database unavailable") from None
    record_dependency(
        "postgres",
        up=True,
        duration_seconds=time.perf_counter() - started,
    )


def check_redis_if_required() -> None:
    """Fail closed on Redis only when production requires it."""
    settings = get_settings()
    if not settings.is_production:
        return
    started = time.perf_counter()
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
        record_dependency(
            "redis",
            up=False,
            duration_seconds=time.perf_counter() - started,
        )
        raise ServiceUnavailableError("redis unavailable") from None
    record_dependency(
        "redis",
        up=True,
        duration_seconds=time.perf_counter() - started,
    )


async def assert_ready() -> None:
    """Raise ``ServiceUnavailableError`` when the app must not receive traffic."""
    if not is_accepting_traffic():
        READINESS.set(0)
        if current_state() is ProcessState.DRAINING:
            raise ServiceUnavailableError("draining")
        raise ServiceUnavailableError("not ready")
    try:
        await check_database()
        check_redis_if_required()
        check_ai_config()
    except Exception:
        READINESS.set(0)
        raise
    READINESS.set(1)


def check_ai_config() -> None:
    """Fail closed when hosted AI is selected without a key. Never calls OpenAI."""
    settings = get_settings()
    if settings.ai_embedding_provider == "openai":
        if not settings.ai_embedding_api_key.get_secret_value().strip():
            raise ServiceUnavailableError("ai embedding not configured")
    from app.core.ai_constants import HOSTED_LLM_PROVIDERS

    if settings.ai_llm_provider in HOSTED_LLM_PROVIDERS:
        if not settings.ai_llm_api_key.get_secret_value().strip():
            raise ServiceUnavailableError("ai llm not configured")
        if (
            settings.ai_llm_provider == "openai_compatible"
            and not settings.ai_llm_base_url.strip()
        ):
            raise ServiceUnavailableError("ai llm not configured")

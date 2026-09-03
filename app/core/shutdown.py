"""Bounded runtime resource cleanup. Failures must not hang process exit."""

from __future__ import annotations

import asyncio
import logging

logger = logging.getLogger("app.lifecycle")

_RESOURCE_CLOSE_SECONDS = 5.0


async def shutdown_runtime_resources() -> None:
    """Close Redis and dispose the SQLAlchemy engine without blocking forever."""
    await _close_rate_limiter()
    await _dispose_engine()


async def _close_rate_limiter() -> None:
    try:
        from app.core.rate_limit import close_rate_limiter

        await asyncio.wait_for(
            asyncio.to_thread(close_rate_limiter),
            timeout=_RESOURCE_CLOSE_SECONDS,
        )
    except TimeoutError:
        logger.warning("event=shutdown component=redis result=timeout")
    except Exception:
        logger.warning("event=shutdown component=redis result=close_error")


async def _dispose_engine() -> None:
    try:
        from app.db import session as db_session

        await asyncio.wait_for(
            db_session.engine.dispose(),
            timeout=_RESOURCE_CLOSE_SECONDS,
        )
    except TimeoutError:
        logger.warning("event=shutdown component=postgres result=timeout")
    except Exception:
        logger.warning("event=shutdown component=postgres result=close_error")

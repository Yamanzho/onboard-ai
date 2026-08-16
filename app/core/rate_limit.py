"""Simple fixed-window rate limiter (Redis-backed).

Development: falls back to process-local memory when Redis is unavailable
(convenient for local work; **not** shared across workers).

Production (``APP_ENV=production``): Redis is required. Connection or command
failures raise ``ServiceUnavailableError`` (HTTP 503) — never silently switch
to per-process memory (which would bypass shared limits across uvicorn workers).
"""

from __future__ import annotations

import logging
import time
from collections import defaultdict
from threading import Lock

from app.core.config import get_settings
from app.core.exceptions import ServiceUnavailableError

logger = logging.getLogger(__name__)

_memory_hits: dict[str, list[float]] = defaultdict(list)
_memory_lock = Lock()
_redis_client = None
_redis_failed = False

_PROD_REDIS_UNAVAILABLE = "Rate limiting temporarily unavailable"


def reset_rate_limiter_state_for_tests() -> None:
    """Clear cached Redis client / failure flags (unit tests only)."""
    global _redis_client, _redis_failed
    _redis_client = None
    _redis_failed = False
    with _memory_lock:
        _memory_hits.clear()


def _get_redis():
    """Lazy Redis client.

    Development: returns ``None`` after a failed connect (memory fallback).
    Production: raises ``ServiceUnavailableError`` — no memory fallback.
    """
    global _redis_client, _redis_failed
    settings = get_settings()

    if settings.is_production:
        if _redis_client is not None:
            return _redis_client
        try:
            from redis import Redis

            client = Redis.from_url(settings.redis_url, decode_responses=True)
            client.ping()
            _redis_client = client
            return _redis_client
        except Exception:
            logger.error(
                "Rate limiter: Redis required when APP_ENV=production but unavailable"
            )
            raise ServiceUnavailableError(_PROD_REDIS_UNAVAILABLE) from None

    if _redis_failed:
        return None
    if _redis_client is not None:
        return _redis_client
    try:
        from redis import Redis

        client = Redis.from_url(settings.redis_url, decode_responses=True)
        client.ping()
        _redis_client = client
        return _redis_client
    except Exception:
        logger.warning(
            "Rate limiter: Redis unavailable, using in-memory fallback "
            "(development only; not shared across workers)"
        )
        _redis_failed = True
        return None


def is_rate_limited(key: str, *, limit: int, window_seconds: int) -> bool:
    """Return True when ``key`` has exceeded ``limit`` hits in the window.

    In production, Redis errors propagate as ``ServiceUnavailableError`` instead
    of falling back to process-local memory.
    """
    if limit <= 0:
        return False

    redis = _get_redis()
    if redis is not None:
        return _redis_is_limited(redis, key, limit=limit, window_seconds=window_seconds)
    return _memory_is_limited(key, limit=limit, window_seconds=window_seconds)


_INCR_EXPIRE_LUA = """
local n = redis.call('INCR', KEYS[1])
if n == 1 or redis.call('TTL', KEYS[1]) < 0 then
  redis.call('EXPIRE', KEYS[1], tonumber(ARGV[1]))
end
return n
"""


def _redis_is_limited(redis, key: str, *, limit: int, window_seconds: int) -> bool:
    redis_key = f"rate_limit:{key}"
    try:
        count = redis.eval(_INCR_EXPIRE_LUA, 1, redis_key, int(window_seconds))
        return int(count) > limit
    except Exception:
        if get_settings().is_production:
            logger.error(
                "Rate limiter: Redis command failed in production; refusing memory fallback"
            )
            raise ServiceUnavailableError(_PROD_REDIS_UNAVAILABLE) from None
        logger.warning("Rate limiter: Redis error, falling back to memory", exc_info=True)
        return _memory_is_limited(key, limit=limit, window_seconds=window_seconds)


def _memory_is_limited(key: str, *, limit: int, window_seconds: int) -> bool:
    now = time.monotonic()
    cutoff = now - window_seconds
    with _memory_lock:
        hits = [ts for ts in _memory_hits[key] if ts >= cutoff]
        hits.append(now)
        _memory_hits[key] = hits
        return len(hits) > limit

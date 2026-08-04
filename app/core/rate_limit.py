"""Simple fixed-window rate limiter (Redis-backed, in-memory fallback)."""

from __future__ import annotations

import logging
import time
from collections import defaultdict
from threading import Lock

from app.core.config import get_settings

logger = logging.getLogger(__name__)

_memory_hits: dict[str, list[float]] = defaultdict(list)
_memory_lock = Lock()
_redis_client = None
_redis_failed = False


def _get_redis():
    """Lazy Redis client; falls back to memory if Redis is unavailable."""
    global _redis_client, _redis_failed
    if _redis_failed:
        return None
    if _redis_client is not None:
        return _redis_client
    try:
        from redis import Redis

        settings = get_settings()
        client = Redis.from_url(settings.redis_url, decode_responses=True)
        client.ping()
        _redis_client = client
        return _redis_client
    except Exception:
        logger.warning("Rate limiter: Redis unavailable, using in-memory fallback")
        _redis_failed = True
        return None


def is_rate_limited(key: str, *, limit: int, window_seconds: int) -> bool:
    """Return True when ``key`` has exceeded ``limit`` hits in the window."""
    if limit <= 0:
        return False

    redis = _get_redis()
    if redis is not None:
        return _redis_is_limited(redis, key, limit=limit, window_seconds=window_seconds)
    return _memory_is_limited(key, limit=limit, window_seconds=window_seconds)


def _redis_is_limited(redis, key: str, *, limit: int, window_seconds: int) -> bool:
    redis_key = f"rate_limit:{key}"
    try:
        count = redis.incr(redis_key)
        if count == 1:
            redis.expire(redis_key, window_seconds)
        return int(count) > limit
    except Exception:
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

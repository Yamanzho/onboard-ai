"""Prometheus instrumentation with bounded, non-sensitive labels."""

from __future__ import annotations

import asyncio
import os
import time
from datetime import UTC, datetime
from typing import Any

from prometheus_client import (
    CONTENT_TYPE_LATEST,
    REGISTRY,
    CollectorRegistry,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
    multiprocess,
)
from sqlalchemy import text

HTTP_REQUESTS = Counter(
    "onboardai_http_requests_total",
    "HTTP requests completed.",
    ("method", "route", "status_class"),
)
HTTP_DURATION = Histogram(
    "onboardai_http_request_duration_seconds",
    "HTTP request duration by normalized route.",
    ("method", "route"),
    buckets=(0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30),
)
HTTP_IN_PROGRESS = Gauge(
    "onboardai_http_requests_in_progress",
    "HTTP requests currently executing.",
    ("method",),
    multiprocess_mode="livesum",
)
READINESS = Gauge(
    "onboardai_readiness",
    "Whether the last readiness evaluation succeeded.",
    multiprocess_mode="livemostrecent",
)
LIFECYCLE_STATE = Gauge(
    "onboardai_lifecycle_state",
    "Process lifecycle: 0=starting, 1=ready, 2=draining, 3=stopped.",
    multiprocess_mode="livemostrecent",
)
DEPENDENCY_UP = Gauge(
    "onboardai_dependency_up",
    "Whether a shallow dependency check succeeded.",
    ("dependency",),
    multiprocess_mode="livemostrecent",
)
DEPENDENCY_LATENCY = Gauge(
    "onboardai_dependency_check_duration_seconds",
    "Duration of the latest shallow dependency check.",
    ("dependency",),
    multiprocess_mode="livemostrecent",
)

AI_PROVIDER_REQUESTS = Counter(
    "onboardai_ai_provider_requests_total",
    "Hosted AI provider requests.",
    ("provider", "model", "operation", "status", "error_category"),
)
AI_PROVIDER_DURATION = Histogram(
    "onboardai_ai_provider_request_duration_seconds",
    "End-to-end hosted provider request duration, including retries.",
    ("provider", "model", "operation"),
    buckets=(0.1, 0.25, 0.5, 1, 2.5, 5, 10, 20, 30, 60),
)
AI_PROVIDER_RETRIES = Counter(
    "onboardai_ai_provider_retries_total",
    "Hosted provider retry attempts.",
    ("provider", "model", "operation", "error_category"),
)
AI_PROVIDER_TOKENS = Counter(
    "onboardai_ai_provider_tokens_total",
    "Tokens reported by a hosted AI provider.",
    ("provider", "model", "operation", "token_type"),
)
IDEMPOTENCY_CLAIMS = Counter(
    "onboardai_idempotency_claims_total",
    "Idempotency claim outcomes.",
    ("operation", "outcome"),
)
IDEMPOTENCY_TRANSITIONS = Counter(
    "onboardai_idempotency_transitions_total",
    "Idempotency terminal transition outcomes.",
    ("operation", "outcome"),
)
OUTBOUND_TRANSITIONS = Counter(
    "onboardai_telegram_outbound_transitions_total",
    "Durable Telegram outbound transition outcomes.",
    ("status", "error_category"),
)
KB_INDEX_RUNS = Counter(
    "onboardai_kb_index_runs_total",
    "Knowledge-base indexing outcomes.",
    ("result", "error_category"),
)

OUTBOUND_MESSAGES = Gauge(
    "onboardai_telegram_outbound_messages",
    "Durable Telegram outbound rows by state.",
    ("status",),
    multiprocess_mode="livemostrecent",
)
OUTBOUND_DUE = Gauge(
    "onboardai_telegram_outbound_due",
    "Pending Telegram outbound rows currently due.",
    multiprocess_mode="livemostrecent",
)
OUTBOUND_STALE_SENDING = Gauge(
    "onboardai_telegram_outbound_stale_sending",
    "Telegram outbound rows with expired sending leases.",
    multiprocess_mode="livemostrecent",
)
OUTBOUND_OLDEST_PENDING_AGE = Gauge(
    "onboardai_telegram_outbound_oldest_pending_age_seconds",
    "Age of the oldest pending Telegram outbound row.",
    multiprocess_mode="livemostrecent",
)
IDEMPOTENCY_STALE = Gauge(
    "onboardai_idempotency_stale_leases",
    "Expired idempotency processing leases.",
    ("operation",),
    multiprocess_mode="livemostrecent",
)
KB_VERSIONS = Gauge(
    "onboardai_kb_current_versions",
    "Current published knowledge versions by index state.",
    ("status",),
    multiprocess_mode="livemostrecent",
)
KB_STALE_INDEXES = Gauge(
    "onboardai_kb_stale_indexes",
    "Current published versions whose latest reindex failed.",
    multiprocess_mode="livemostrecent",
)
KB_STALE_INDEXING = Gauge(
    "onboardai_kb_stale_indexing_leases",
    "Current published versions with expired indexing leases.",
    multiprocess_mode="livemostrecent",
)
KB_OLDEST_INDEXING_AGE = Gauge(
    "onboardai_kb_oldest_indexing_age_seconds",
    "Age of the oldest current indexing operation.",
    multiprocess_mode="livemostrecent",
)
KB_REINDEX_REQUIRED = Gauge(
    "onboardai_kb_reindex_required",
    "Current indexed versions incompatible with active embedding configuration.",
    multiprocess_mode="livemostrecent",
)
BOT_HEARTBEAT_UP = Gauge(
    "onboardai_telegram_bot_heartbeat_up",
    "Whether the Telegram bot heartbeat is fresh.",
    multiprocess_mode="livemostrecent",
)
BOT_HEARTBEAT_AGE = Gauge(
    "onboardai_telegram_bot_heartbeat_age_seconds",
    "Age of the latest Telegram bot heartbeat.",
    multiprocess_mode="livemostrecent",
)

BOT_HEARTBEAT_KEY = "onboardai:monitoring:bot_heartbeat"
BOT_HEARTBEAT_TTL_SECONDS = 90
_DB_STATUS_VALUES = ("pending", "sending", "sent", "failed")
_KB_STATUS_VALUES = ("pending", "indexing", "indexed", "failed")
_IDEMPOTENCY_OPERATIONS = ("telegram-update", "ai-chat")
_refresh_lock = asyncio.Lock()


def normalized_route(scope: dict[str, Any]) -> str:
    """Return a route template, never a raw URL containing identifiers."""
    route = scope.get("route")
    path = getattr(route, "path", None)
    if isinstance(path, str) and path:
        return path
    return "unmatched"


def record_dependency(name: str, *, up: bool, duration_seconds: float) -> None:
    if name not in {"postgres", "redis"}:
        return
    DEPENDENCY_UP.labels(dependency=name).set(1 if up else 0)
    DEPENDENCY_LATENCY.labels(dependency=name).set(max(0.0, duration_seconds))


def record_provider_result(
    *,
    model: str,
    operation: str,
    status: str,
    error_category: str = "none",
    duration_seconds: float,
) -> None:
    safe_operation = operation if operation in {"embed", "llm"} else "unknown"
    safe_status = status if status in {"success", "error", "timeout"} else "error"
    safe_error = error_category if error_category in {
        "none",
        "timeout",
        "network",
        "rate_limit",
        "server_error",
        "credentials",
        "invalid_json",
        "invalid_schema",
        "unknown",
    } else "unknown"
    safe_model = (model.strip() or "unknown")[:80]
    AI_PROVIDER_REQUESTS.labels(
        provider="openai",
        model=safe_model,
        operation=safe_operation,
        status=safe_status,
        error_category=safe_error,
    ).inc()
    AI_PROVIDER_DURATION.labels(
        provider="openai",
        model=safe_model,
        operation=safe_operation,
    ).observe(max(0.0, duration_seconds))


def record_provider_retry(*, model: str, operation: str, error_category: str) -> None:
    safe_error = error_category if error_category in {
        "timeout", "network", "rate_limit", "server_error"
    } else "unknown"
    AI_PROVIDER_RETRIES.labels(
        provider="openai",
        model=(model.strip() or "unknown")[:80],
        operation=operation if operation in {"embed", "llm"} else "unknown",
        error_category=safe_error,
    ).inc()


def record_provider_usage(*, model: str, operation: str, usage: object) -> None:
    if not isinstance(usage, dict):
        return
    mapping = {
        "input": usage.get("prompt_tokens", usage.get("input_tokens")),
        "output": usage.get("completion_tokens", usage.get("output_tokens")),
        "total": usage.get("total_tokens"),
    }
    for token_type, value in mapping.items():
        if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
            AI_PROVIDER_TOKENS.labels(
                provider="openai",
                model=(model.strip() or "unknown")[:80],
                operation=operation if operation in {"embed", "llm"} else "unknown",
                token_type=token_type,
            ).inc(value)


async def _refresh_database_metrics() -> None:
    from app.core.config import get_settings
    from app.db.uow import UnitOfWork

    started = time.perf_counter()
    settings = get_settings()
    try:
        async with UnitOfWork() as uow:
            await uow.enter_platform()
            row = (
                await uow.session.execute(
                    text(
                        """
                        SELECT
                          count(*) FILTER (WHERE o.status = 'pending') AS o_pending,
                          count(*) FILTER (WHERE o.status = 'sending') AS o_sending,
                          count(*) FILTER (WHERE o.status = 'sent') AS o_sent,
                          count(*) FILTER (WHERE o.status = 'failed') AS o_failed,
                          count(*) FILTER (
                            WHERE o.status = 'pending' AND o.next_attempt_at <= now()
                              AND o.attempt_count < 8
                          ) AS o_due,
                          count(*) FILTER (
                            WHERE o.status = 'sending' AND o.lease_expires_at < now()
                          ) AS o_stale,
                          coalesce(max(extract(epoch FROM now() - o.created_at))
                            FILTER (WHERE o.status = 'pending'), 0) AS o_oldest
                        FROM telegram_outbound_messages o
                        """
                    )
                )
            ).mappings().one()
            for status in _DB_STATUS_VALUES:
                OUTBOUND_MESSAGES.labels(status=status).set(float(row[f"o_{status}"] or 0))
            OUTBOUND_DUE.set(float(row["o_due"] or 0))
            OUTBOUND_STALE_SENDING.set(float(row["o_stale"] or 0))
            OUTBOUND_OLDEST_PENDING_AGE.set(float(row["o_oldest"] or 0))

            idem_rows = (
                await uow.session.execute(
                    text(
                        """
                        SELECT operation, count(*) AS count
                        FROM idempotency_receipts
                        WHERE status = 'processing' AND lease_expires_at < now()
                          AND operation IN ('telegram-update', 'ai-chat')
                        GROUP BY operation
                        """
                    )
                )
            ).mappings()
            idem = {str(item["operation"]): int(item["count"]) for item in idem_rows}
            for operation in _IDEMPOTENCY_OPERATIONS:
                IDEMPOTENCY_STALE.labels(operation=operation).set(idem.get(operation, 0))

            kb = (
                await uow.session.execute(
                    text(
                        """
                        SELECT
                          count(*) FILTER (WHERE v.index_status = 'pending') AS pending,
                          count(*) FILTER (WHERE v.index_status = 'indexing') AS indexing,
                          count(*) FILTER (WHERE v.index_status = 'indexed') AS indexed,
                          count(*) FILTER (WHERE v.index_status = 'failed') AS failed,
                          count(*) FILTER (
                            WHERE v.index_status = 'indexing'
                              AND v.indexing_lease_expires_at < now()
                          ) AS stale_indexing,
                          count(*) FILTER (
                            WHERE v.index_status = 'indexed'
                              AND v.indexing_failed_at IS NOT NULL
                              AND v.indexed_at IS NOT NULL
                              AND v.indexing_failed_at > v.indexed_at
                          ) AS stale_indexes,
                          coalesce(max(extract(epoch FROM now() - v.indexing_started_at))
                            FILTER (WHERE v.index_status = 'indexing'), 0) AS oldest_indexing,
                          count(*) FILTER (
                            WHERE v.index_status = 'indexed' AND (
                              v.embedding_provider IS DISTINCT FROM :provider OR
                              v.embedding_model IS DISTINCT FROM :model OR
                              v.embedding_dimension IS DISTINCT FROM :dimension
                            )
                          ) AS incompatible
                        FROM knowledge_articles a
                        JOIN knowledge_article_versions v ON v.id = a.current_version_id
                        WHERE a.status = 'published'
                        """
                    ),
                    {
                        "provider": settings.ai_embedding_provider,
                        "model": settings.ai_embedding_model,
                        "dimension": settings.ai_embedding_dimension,
                    },
                )
            ).mappings().one()
            for status in _KB_STATUS_VALUES:
                KB_VERSIONS.labels(status=status).set(float(kb[status] or 0))
            KB_STALE_INDEXING.set(float(kb["stale_indexing"] or 0))
            KB_STALE_INDEXES.set(float(kb["stale_indexes"] or 0))
            KB_OLDEST_INDEXING_AGE.set(float(kb["oldest_indexing"] or 0))
            KB_REINDEX_REQUIRED.set(float(kb["incompatible"] or 0))
        record_dependency(
            "postgres",
            up=True,
            duration_seconds=time.perf_counter() - started,
        )
    except Exception:
        record_dependency(
            "postgres",
            up=False,
            duration_seconds=time.perf_counter() - started,
        )


async def _refresh_redis_metrics() -> None:
    from redis.asyncio import Redis

    from app.core.config import get_settings

    started = time.perf_counter()
    client: Redis | None = None
    try:
        client = Redis.from_url(
            get_settings().redis_url,
            socket_connect_timeout=2,
            socket_timeout=2,
            decode_responses=True,
        )
        await client.ping()
        value = await client.get(BOT_HEARTBEAT_KEY)
        now = datetime.now(UTC).timestamp()
        heartbeat = float(value) if value is not None else 0.0
        age = max(0.0, now - heartbeat) if heartbeat > 0 else BOT_HEARTBEAT_TTL_SECONDS + 1
        BOT_HEARTBEAT_AGE.set(age)
        BOT_HEARTBEAT_UP.set(1 if age <= BOT_HEARTBEAT_TTL_SECONDS else 0)
        record_dependency(
            "redis",
            up=True,
            duration_seconds=time.perf_counter() - started,
        )
    except Exception:
        BOT_HEARTBEAT_UP.set(0)
        record_dependency(
            "redis",
            up=False,
            duration_seconds=time.perf_counter() - started,
        )
    finally:
        if client is not None:
            await client.aclose()


async def refresh_durable_metrics() -> None:
    """Refresh gauges from durable state without making scrape failure contagious."""
    async with _refresh_lock:
        await asyncio.gather(_refresh_database_metrics(), _refresh_redis_metrics())


async def prometheus_payload() -> tuple[bytes, str]:
    await refresh_durable_metrics()
    directory = os.environ.get("PROMETHEUS_MULTIPROC_DIR")
    if directory:
        registry = CollectorRegistry()
        multiprocess.MultiProcessCollector(registry)
    else:
        registry = REGISTRY
    return generate_latest(registry), CONTENT_TYPE_LATEST

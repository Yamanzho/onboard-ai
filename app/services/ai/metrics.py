"""In-process AI instrumentation. No Prometheus. Labels are bounded enums."""

from __future__ import annotations

from threading import Lock
from typing import Any

_ALLOWED_PROVIDERS = frozenset({"fake", "openai", "none"})
_ALLOWED_OPERATIONS = frozenset({"chat", "retrieve", "embed", "llm"})
_ALLOWED_RESULTS = frozenset(
    {
        "answered",
        "empty_retrieval",
        "no_answer",
        "error",
        "rate_limited",
        "timeout",
        "forbidden",
        "success",
    }
)
_ALLOWED_ERROR_CLASSES = frozenset(
    {
        "",
        "timeout",
        "network",
        "rate_limit",
        "server_error",
        "credentials",
        "invalid_json",
        "invalid_schema",
        "unknown",
    }
)

_lock = Lock()
_counters: dict[str, int] = {}
_latency_ms_sum: dict[str, float] = {}
_latency_ms_count: dict[str, int] = {}
_hit_count_sum = 0
_hit_count_n = 0


def reset_ai_metrics_for_tests() -> None:
    global _hit_count_sum, _hit_count_n
    with _lock:
        _counters.clear()
        _latency_ms_sum.clear()
        _latency_ms_count.clear()
        _hit_count_sum = 0
        _hit_count_n = 0


def _bound(value: str, allowed: frozenset[str], default: str) -> str:
    return value if value in allowed else default


def incr(
    name: str,
    *,
    provider: str = "none",
    operation: str = "chat",
    result: str = "success",
    error_class: str = "",
    amount: int = 1,
) -> None:
    provider = _bound(provider, _ALLOWED_PROVIDERS, "none")
    operation = _bound(operation, _ALLOWED_OPERATIONS, "chat")
    result = _bound(result, _ALLOWED_RESULTS, "error")
    error_class = _bound(error_class, _ALLOWED_ERROR_CLASSES, "unknown")
    key = f"{name}|{provider}|{operation}|{result}|{error_class}"
    with _lock:
        _counters[key] = _counters.get(key, 0) + amount


def observe_latency_ms(operation: str, duration_ms: float) -> None:
    operation = _bound(operation, _ALLOWED_OPERATIONS, "chat")
    with _lock:
        _latency_ms_sum[operation] = _latency_ms_sum.get(operation, 0.0) + duration_ms
        _latency_ms_count[operation] = _latency_ms_count.get(operation, 0) + 1


def observe_hit_count(hit_count: int) -> None:
    global _hit_count_sum, _hit_count_n
    with _lock:
        _hit_count_sum += max(0, int(hit_count))
        _hit_count_n += 1


def snapshot() -> dict[str, Any]:
    with _lock:
        return {
            "counters": dict(_counters),
            "latency_ms_sum": dict(_latency_ms_sum),
            "latency_ms_count": dict(_latency_ms_count),
            "hit_count_sum": _hit_count_sum,
            "hit_count_n": _hit_count_n,
        }


def counter_value(
    name: str,
    *,
    provider: str = "none",
    operation: str = "chat",
    result: str = "success",
    error_class: str = "",
) -> int:
    key = f"{name}|{provider}|{operation}|{result}|{error_class}"
    with _lock:
        return _counters.get(key, 0)

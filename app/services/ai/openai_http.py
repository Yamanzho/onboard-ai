"""Shared OpenAI HTTP transport: classify errors, bound retries, never log secrets."""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass
from typing import Any, Literal

import httpx

from app.core.config import get_settings
from app.core.exceptions import ServiceUnavailableError, ValidationError
from app.core.request_id import request_id_log_value
from app.services.ai.metrics import incr, observe_latency_ms

Kind = Literal["embedding", "llm"]

_KIND_LABEL = {
    "embedding": "embedding provider",
    "llm": "LLM provider",
}
_KIND_LOGGER = {
    "embedding": "app.kb.embed",
    "llm": "app.kb.llm",
}
_KIND_OPERATION = {
    "embedding": "embed",
    "llm": "llm",
}


@dataclass(frozen=True, slots=True)
class ProviderFailure(Exception):
    """Internal OpenAI failure. Converted to AppError at the provider boundary."""

    user_message: str
    error_class: str
    retryable: bool
    status_code: int | None = None
    retry_after: float | None = None

    def __str__(self) -> str:
        return self.user_message

    def reraise_app(self) -> None:
        if self.error_class == "credentials":
            raise ValidationError(self.user_message)
        raise ServiceUnavailableError(self.user_message)


async def retry_sleep(seconds: float) -> None:
    """Backoff sleep. Tests patch this to avoid real delays."""
    if seconds > 0:
        await asyncio.sleep(seconds)


def parse_retry_after_seconds(response: httpx.Response, *, cap: float) -> float | None:
    raw = response.headers.get("Retry-After")
    if raw is None:
        return None
    stripped = raw.strip()
    if not stripped.isdigit():
        return None
    return min(float(int(stripped)), cap)


def classify_openai_response(response: httpx.Response, *, kind: Kind) -> dict[str, Any]:
    """Parse a successful JSON body or raise ``ProviderFailure``. Never logs the body."""
    label = _KIND_LABEL[kind]
    status = response.status_code
    if status in {401, 403}:
        raise ProviderFailure(
            user_message=f"{label} rejected credentials",
            error_class="credentials",
            retryable=False,
            status_code=status,
        )
    if status == 429:
        settings = get_settings()
        raise ProviderFailure(
            user_message=f"{label} unavailable",
            error_class="rate_limit",
            retryable=True,
            status_code=status,
            retry_after=parse_retry_after_seconds(
                response,
                cap=settings.ai_provider_retry_max_backoff_seconds,
            ),
        )
    if status >= 500:
        raise ProviderFailure(
            user_message=f"{label} unavailable",
            error_class="server_error",
            retryable=True,
            status_code=status,
        )
    if status >= 400:
        raise ProviderFailure(
            user_message=f"{label} request failed",
            error_class="unknown",
            retryable=False,
            status_code=status,
        )
    try:
        body = response.json()
    except ValueError as exc:
        raise ProviderFailure(
            user_message=f"{label} returned invalid JSON",
            error_class="invalid_json",
            retryable=False,
            status_code=status,
        ) from exc
    if not isinstance(body, dict):
        raise ProviderFailure(
            user_message=f"{label} returned invalid JSON",
            error_class="invalid_json",
            retryable=False,
            status_code=status,
        )
    return body


def raise_as_app_error(response: httpx.Response, *, kind: Kind) -> dict[str, Any]:
    """Compatibility wrapper used by existing provider unit tests."""
    try:
        return classify_openai_response(response, kind=kind)
    except ProviderFailure as exc:
        exc.reraise_app()
        raise AssertionError("unreachable") from exc


def _delay_for(
    failure: ProviderFailure,
    *,
    retries_done: int,
    backoff: float,
    cap: float,
) -> float:
    delay = min(backoff * (2**retries_done), cap)
    if failure.retry_after is not None:
        delay = min(max(failure.retry_after, 0.0), cap)
    return delay


def _record_failure(
    kind: Kind,
    failure: ProviderFailure,
    *,
    retry_count: int,
    started: float,
) -> None:
    operation = _KIND_OPERATION[kind]
    duration_ms = (time.perf_counter() - started) * 1000
    observe_latency_ms(operation, duration_ms)
    incr(
        "ai_provider_errors",
        provider="openai",
        operation=operation,
        result="error",
        error_class=failure.error_class,
    )
    logging.getLogger(_KIND_LOGGER[kind]).info(
        "kb_%s_openai request_id=%s provider=openai operation=%s "
        "result=error error_class=%s status=%s retry_count=%s duration_ms=%.1f",
        operation,
        request_id_log_value(),
        operation,
        failure.error_class,
        failure.status_code if failure.status_code is not None else "-",
        retry_count,
        duration_ms,
    )


async def post_openai_json(
    url: str,
    headers: dict[str, str],
    payload: dict[str, Any],
    *,
    timeout: float,
    kind: Kind,
) -> dict[str, Any]:
    """POST JSON to OpenAI with bounded retries. Never logs key, prompt, or body."""
    settings = get_settings()
    max_retries = settings.ai_provider_max_retries
    backoff = settings.ai_provider_retry_backoff_seconds
    cap = settings.ai_provider_retry_max_backoff_seconds
    operation = _KIND_OPERATION[kind]
    started = time.perf_counter()
    attempts = 0
    last_failure: ProviderFailure | None = None

    while True:
        attempts += 1
        try:
            async with httpx.AsyncClient(timeout=timeout) as client:
                response = await client.post(url, headers=headers, json=payload)
            body = classify_openai_response(response, kind=kind)
        except httpx.TimeoutException as exc:
            last_failure = ProviderFailure(
                user_message=f"{_KIND_LABEL[kind]} timed out",
                error_class="timeout",
                retryable=True,
            )
            failure_exc: BaseException = exc
        except httpx.HTTPError as exc:
            last_failure = ProviderFailure(
                user_message=f"{_KIND_LABEL[kind]} unavailable",
                error_class="network",
                retryable=True,
            )
            failure_exc = exc
        except ProviderFailure as exc:
            last_failure = exc
            failure_exc = exc
        else:
            duration_ms = (time.perf_counter() - started) * 1000
            observe_latency_ms(operation, duration_ms)
            incr(
                "ai_provider_requests",
                provider="openai",
                operation=operation,
                result="success",
            )
            logging.getLogger(_KIND_LOGGER[kind]).info(
                "kb_%s_openai request_id=%s provider=openai operation=%s "
                "result=success retry_count=%s duration_ms=%.1f",
                operation,
                request_id_log_value(),
                operation,
                attempts - 1,
                duration_ms,
            )
            return body

        retries_done = attempts - 1
        if last_failure is None or not last_failure.retryable or retries_done >= max_retries:
            _record_failure(
                kind,
                last_failure or ProviderFailure("unknown", "unknown", False),
                retry_count=retries_done,
                started=started,
            )
            if last_failure is not None:
                raise last_failure from failure_exc
            raise failure_exc

        await retry_sleep(
            _delay_for(
                last_failure,
                retries_done=retries_done,
                backoff=backoff,
                cap=cap,
            )
        )
        incr("ai_retries", provider="openai", operation=operation, result="error")

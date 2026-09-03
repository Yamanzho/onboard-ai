"""Attach an opaque X-Request-ID to every HTTP request."""

from __future__ import annotations

import logging
import time

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.core.metrics import (
    HTTP_DURATION,
    HTTP_IN_PROGRESS,
    HTTP_REQUESTS,
    normalized_route,
)
from app.core.request_id import bind_request_id, parse_request_id, reset_request_id

logger = logging.getLogger("app.http")


class RequestIdMiddleware(BaseHTTPMiddleware):
    """Correlate HTTP → AIChatService → retriever → LLM without identity data."""

    async def dispatch(self, request: Request, call_next) -> Response:
        request_id = parse_request_id(request.headers.get("X-Request-ID"))
        token = bind_request_id(request_id)
        method = request.method.upper()
        started = time.perf_counter()
        HTTP_IN_PROGRESS.labels(method=method).inc()
        try:
            try:
                response = await call_next(request)
            finally:
                HTTP_IN_PROGRESS.labels(method=method).dec()
            route = normalized_route(request.scope)
            duration = time.perf_counter() - started
            status_class = f"{response.status_code // 100}xx"
            HTTP_REQUESTS.labels(
                method=method,
                route=route,
                status_class=status_class,
            ).inc()
            HTTP_DURATION.labels(method=method, route=route).observe(duration)
            logger.info(
                "event=http_request request_id=%s method=%s route=%s status=%s "
                "duration_ms=%.1f",
                request_id,
                method,
                route,
                response.status_code,
                duration * 1000,
            )
            response.headers["X-Request-ID"] = request_id
            return response
        finally:
            reset_request_id(token)

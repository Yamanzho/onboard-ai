"""Attach an opaque X-Request-ID to every HTTP request."""

from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

from app.core.request_id import bind_request_id, parse_request_id, reset_request_id


class RequestIdMiddleware(BaseHTTPMiddleware):
    """Correlate HTTP → AIChatService → retriever → LLM without identity data."""

    async def dispatch(self, request: Request, call_next) -> Response:
        request_id = parse_request_id(request.headers.get("X-Request-ID"))
        token = bind_request_id(request_id)
        try:
            response = await call_next(request)
        finally:
            reset_request_id(token)
        response.headers["X-Request-ID"] = request_id
        return response

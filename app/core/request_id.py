"""Opaque request correlation IDs. Never derived from identity or the question."""

from __future__ import annotations

import re
from contextvars import ContextVar, Token
from uuid import uuid4

_REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9_-]{8,64}$")
_request_id_var: ContextVar[str | None] = ContextVar("onboard_request_id", default=None)


def new_request_id() -> str:
    return str(uuid4())


def parse_request_id(raw: str | None) -> str:
    """Accept a client-supplied opaque id, or generate one.

    JWT / dotted strings are rejected so the id cannot carry credentials.
    """
    if raw is None:
        return new_request_id()
    stripped = raw.strip()
    if not stripped or "." in stripped or " " in stripped:
        return new_request_id()
    if _REQUEST_ID_RE.fullmatch(stripped):
        return stripped
    return new_request_id()


def read_request_id(raw: str | None) -> str | None:
    """Extract a valid id without generating a replacement."""
    if raw is None:
        return None
    stripped = raw.strip()
    if _REQUEST_ID_RE.fullmatch(stripped) and "." not in stripped:
        return stripped
    return None


def get_request_id() -> str | None:
    return _request_id_var.get()


def bind_request_id(request_id: str) -> Token[str | None]:
    return _request_id_var.set(request_id)


def reset_request_id(token: Token[str | None]) -> None:
    _request_id_var.reset(token)


def request_id_log_value() -> str:
    return get_request_id() or "-"

"""Opaque request IDs must not carry identity or credentials."""

from __future__ import annotations

from app.core.request_id import new_request_id, parse_request_id, read_request_id


def test_generated_id_is_opaque_uuid() -> None:
    value = new_request_id()
    assert len(value) >= 32
    assert "." not in value
    assert " " not in value


def test_parse_rejects_jwt_like_values() -> None:
    jwt = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjMifQ.signature"
    parsed = parse_request_id(jwt)
    assert parsed != jwt
    assert "." not in parsed


def test_parse_accepts_uuid() -> None:
    raw = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
    assert parse_request_id(raw) == raw


def test_read_request_id_does_not_invent() -> None:
    assert read_request_id(None) is None
    assert read_request_id("bad id") is None
    assert read_request_id("req-ok-correlation-01") == "req-ok-correlation-01"

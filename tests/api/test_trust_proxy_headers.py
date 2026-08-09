"""Trust-proxy / client-IP policy for rate limits (P0-01 / SEC-R1)."""

from __future__ import annotations

from uuid import uuid4

import pytest
from httpx import ASGITransport, AsyncClient
from starlette.requests import Request

from app.core.client_ip import client_ip
from app.core.config import get_settings
from app.core.rate_limit import is_rate_limited, reset_rate_limiter_state_for_tests
from app.main import app


def _request(
    *,
    client_host: str = "203.0.113.10",
    forwarded_for: str | None = None,
    real_ip: str | None = None,
) -> Request:
    headers: list[tuple[bytes, bytes]] = []
    if forwarded_for is not None:
        headers.append((b"x-forwarded-for", forwarded_for.encode("latin-1")))
    if real_ip is not None:
        headers.append((b"x-real-ip", real_ip.encode("latin-1")))
    scope = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "POST",
        "scheme": "http",
        "path": "/api/v1/auth/login",
        "raw_path": b"/api/v1/auth/login",
        "query_string": b"",
        "headers": headers,
        "client": (client_host, 54321),
        "server": ("testserver", 80),
    }
    return Request(scope)


@pytest.fixture
def restore_trust_proxy() -> None:
    settings = get_settings()
    previous = settings.trust_proxy_headers
    try:
        yield
    finally:
        settings.trust_proxy_headers = previous


def test_client_ip_ignores_forwarded_headers_when_trust_disabled(
    restore_trust_proxy: None,
) -> None:
    settings = get_settings()
    settings.trust_proxy_headers = False

    req = _request(
        client_host="198.51.100.20",
        forwarded_for="203.0.113.99, 10.0.0.1",
        real_ip="203.0.113.88",
    )
    assert client_ip(req) == "198.51.100.20"


def test_client_ip_uses_x_forwarded_for_when_trust_enabled_and_no_real_ip(
    restore_trust_proxy: None,
) -> None:
    """Nginx-overwrite path: single XFF value is the peer address."""
    settings = get_settings()
    settings.trust_proxy_headers = True

    req = _request(
        client_host="198.51.100.20",
        forwarded_for="203.0.113.99",
    )
    assert client_ip(req) == "203.0.113.99"


def test_client_ip_uses_rightmost_xff_when_trust_enabled_and_chain_present(
    restore_trust_proxy: None,
) -> None:
    """Misconfigured append proxy: prefer immediate peer (rightmost), not spoof."""
    settings = get_settings()
    settings.trust_proxy_headers = True

    req = _request(
        client_host="198.51.100.20",
        forwarded_for="203.0.113.99, 10.0.0.1",
    )
    assert client_ip(req) == "10.0.0.1"


def test_client_ip_prefers_x_real_ip_over_spoofed_xff_when_trust_enabled(
    restore_trust_proxy: None,
) -> None:
    """Trusted nginx sets X-Real-IP=$remote_addr; client XFF must not win."""
    settings = get_settings()
    settings.trust_proxy_headers = True

    req = _request(
        client_host="198.51.100.20",
        forwarded_for="203.0.113.99, 1.2.3.4",
        real_ip="198.51.100.20",
    )
    assert client_ip(req) == "198.51.100.20"


def test_client_ip_uses_x_real_ip_when_trust_enabled_and_no_xff(
    restore_trust_proxy: None,
) -> None:
    settings = get_settings()
    settings.trust_proxy_headers = True

    req = _request(client_host="198.51.100.20", real_ip="203.0.113.77")
    assert client_ip(req) == "203.0.113.77"


def test_rate_limit_not_bypassed_by_xff_when_trust_disabled(
    restore_trust_proxy: None,
) -> None:
    """Spoofed X-Forwarded-For must not create a fresh rate-limit bucket."""
    settings = get_settings()
    settings.trust_proxy_headers = False

    client_host = f"198.51.100.{uuid4().int % 200 + 1}"
    bucket_prefix = f"test_xff_bypass:{uuid4().hex}"

    def _hit(forwarded: str | None) -> bool:
        ip = client_ip(
            _request(client_host=client_host, forwarded_for=forwarded),
        )
        return is_rate_limited(
            f"{bucket_prefix}:ip:{ip}",
            limit=2,
            window_seconds=60,
        )

    assert _hit("1.1.1.1") is False
    assert _hit("2.2.2.2") is False
    # Third attempt with yet another spoofed XFF still counts against real client IP.
    assert _hit("3.3.3.3") is True


def test_rate_limit_not_bypassed_by_xff_when_trust_enabled_with_real_ip(
    restore_trust_proxy: None,
) -> None:
    """SEC-R1: with trust on, spoofed XFF must not open a new bucket (nginx X-Real-IP)."""
    settings = get_settings()
    settings.trust_proxy_headers = True

    peer = f"198.51.100.{uuid4().int % 200 + 1}"
    bucket_prefix = f"test_xff_trust_on:{uuid4().hex}"

    def _hit(forwarded: str) -> bool:
        ip = client_ip(
            _request(
                client_host=peer,
                forwarded_for=forwarded,
                real_ip=peer,
            ),
        )
        return is_rate_limited(
            f"{bucket_prefix}:ip:{ip}",
            limit=2,
            window_seconds=60,
        )

    assert _hit("1.1.1.1") is False
    assert _hit("2.2.2.2") is False
    assert _hit("3.3.3.3") is True


@pytest.mark.asyncio
async def test_login_rate_limit_ignores_xff_when_trust_disabled(
    restore_trust_proxy: None,
) -> None:
    """HTTP login: rotating X-Forwarded-For must not bypass the IP limit."""
    settings = get_settings()
    previous_limit = settings.login_rate_limit
    previous_window = settings.login_rate_window_seconds
    settings.trust_proxy_headers = False
    settings.login_rate_limit = 2
    settings.login_rate_window_seconds = 60

    # Unique ASGI client host so Redis/memory buckets from other tests do not collide.
    client_host = f"198.51.100.{(uuid4().int % 200) + 1}"
    transport = ASGITransport(app=app, client=(client_host, 54321))
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            statuses: list[int] = []
            for i in range(3):
                res = await client.post(
                    "/api/v1/auth/login",
                    data={
                        "username": str(uuid4()),
                        "password": "not-the-password",
                    },
                    headers={"X-Forwarded-For": f"203.0.113.{i + 50}"},
                )
                statuses.append(res.status_code)
    finally:
        settings.login_rate_limit = previous_limit
        settings.login_rate_window_seconds = previous_window

    # First two attempts authenticate (fail credentials → 401); third is rate-limited.
    assert statuses[0] == 401
    assert statuses[1] == 401
    assert statuses[2] == 429


@pytest.mark.asyncio
async def test_login_rate_limit_ignores_spoofed_xff_when_trust_enabled(
    restore_trust_proxy: None,
) -> None:
    """SEC-R1 adversarial: trust on + nginx X-Real-IP; rotating XFF cannot bypass."""
    reset_rate_limiter_state_for_tests()
    settings = get_settings()
    previous_limit = settings.login_rate_limit
    previous_window = settings.login_rate_window_seconds
    settings.trust_proxy_headers = True
    settings.login_rate_limit = 2
    settings.login_rate_window_seconds = 60

    peer = f"198.51.100.{(uuid4().int % 200) + 1}"
    transport = ASGITransport(app=app, client=(peer, 54321))
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            statuses: list[int] = []
            for i in range(3):
                res = await client.post(
                    "/api/v1/auth/login",
                    data={
                        "username": str(uuid4()),
                        "password": "not-the-password",
                    },
                    headers={
                        # Spoofed client-controlled chain (pre-nginx append world).
                        "X-Forwarded-For": f"203.0.113.{i + 50}, 198.18.0.{i}",
                        # Trusted proxy overwrite contract (nginx $remote_addr).
                        "X-Real-IP": peer,
                    },
                )
                statuses.append(res.status_code)
    finally:
        reset_rate_limiter_state_for_tests()
        settings.login_rate_limit = previous_limit
        settings.login_rate_window_seconds = previous_window
        settings.trust_proxy_headers = False

    assert statuses[0] == 401
    assert statuses[1] == 401
    assert statuses[2] == 429


@pytest.mark.asyncio
async def test_invite_preview_rate_limit_ignores_spoofed_xff_when_trust_enabled(
    restore_trust_proxy: None,
) -> None:
    reset_rate_limiter_state_for_tests()
    settings = get_settings()
    previous_limit = settings.invite_preview_rate_limit
    previous_window = settings.invite_preview_rate_window_seconds
    settings.trust_proxy_headers = True
    settings.invite_preview_rate_limit = 2
    settings.invite_preview_rate_window_seconds = 60

    peer = f"198.51.100.{(uuid4().int % 200) + 1}"
    transport = ASGITransport(app=app, client=(peer, 54321))
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            statuses: list[int] = []
            for i in range(3):
                res = await client.post(
                    "/api/v1/auth/invite/preview",
                    json={"token": f"not-a-real-token-{uuid4().hex}"},
                    headers={
                        "X-Forwarded-For": f"198.51.100.{i + 10}",
                        "X-Real-IP": peer,
                    },
                )
                statuses.append(res.status_code)
    finally:
        reset_rate_limiter_state_for_tests()
        settings.invite_preview_rate_limit = previous_limit
        settings.invite_preview_rate_window_seconds = previous_window
        settings.trust_proxy_headers = False

    # First two: invite not found (404); third: rate limited.
    assert statuses[0] == 404
    assert statuses[1] == 404
    assert statuses[2] == 429


@pytest.mark.asyncio
async def test_bot_login_rate_limit_ignores_spoofed_xff_when_trust_enabled(
    restore_trust_proxy: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reset_rate_limiter_state_for_tests()
    settings = get_settings()
    previous_limit = settings.bot_login_rate_limit
    previous_window = settings.bot_login_rate_window_seconds
    settings.trust_proxy_headers = True
    settings.bot_login_rate_limit = 2
    settings.bot_login_rate_window_seconds = 60
    monkeypatch.setattr(settings, "bot_service_token", "test-bot-service-token-32chars!!")
    monkeypatch.setattr(settings, "bot_company_id", str(uuid4()))

    peer = f"198.51.100.{(uuid4().int % 200) + 1}"
    transport = ASGITransport(app=app, client=(peer, 54321))
    company_id = settings.bot_company_id
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            statuses: list[int] = []
            for i in range(3):
                res = await client.post(
                    "/api/v1/auth/bot/telegram",
                    json={
                        "company_id": company_id,
                        "telegram_user_id": 9_000_000 + i,
                    },
                    headers={
                        "X-Bot-Service-Token": "wrong-token",
                        "X-Forwarded-For": f"203.0.113.{i + 1}",
                        "X-Real-IP": peer,
                    },
                )
                statuses.append(res.status_code)
    finally:
        reset_rate_limiter_state_for_tests()
        settings.bot_login_rate_limit = previous_limit
        settings.bot_login_rate_window_seconds = previous_window
        settings.trust_proxy_headers = False

    # Invalid token → 401 for first two; third hits bot_login rate limit.
    assert statuses[0] == 401
    assert statuses[1] == 401
    assert statuses[2] == 429


@pytest.mark.asyncio
async def test_super_admin_login_rate_limit_ignores_spoofed_xff_when_trust_enabled(
    restore_trust_proxy: None,
) -> None:
    reset_rate_limiter_state_for_tests()
    settings = get_settings()
    previous_limit = settings.login_rate_limit
    previous_window = settings.login_rate_window_seconds
    settings.trust_proxy_headers = True
    settings.login_rate_limit = 2
    settings.login_rate_window_seconds = 60

    peer = f"198.51.100.{(uuid4().int % 200) + 1}"
    transport = ASGITransport(app=app, client=(peer, 54321))
    try:
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            statuses: list[int] = []
            for i in range(3):
                res = await client.post(
                    "/api/v1/super-admin/auth/login",
                    json={
                        "email": f"attacker-{i}@example.com",
                        "password": "wrong-password",
                    },
                    headers={
                        "X-Forwarded-For": f"203.0.113.{i + 80}",
                        "X-Real-IP": peer,
                    },
                )
                statuses.append(res.status_code)
    finally:
        reset_rate_limiter_state_for_tests()
        settings.login_rate_limit = previous_limit
        settings.login_rate_window_seconds = previous_window
        settings.trust_proxy_headers = False

    assert statuses[0] == 401
    assert statuses[1] == 401
    assert statuses[2] == 429

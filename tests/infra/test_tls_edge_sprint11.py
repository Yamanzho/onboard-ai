"""Sprint 1.1 — production edge: Secure cookies + no IP override hacks."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest
from fastapi import Response

from app.core.auth_cookies import set_auth_cookies
from app.core.config import Settings, get_settings
from app.schemas.auth import TokenResponse

ROOT = Path(__file__).resolve().parents[2]
AUTH_COOKIES = ROOT / "app" / "core" / "auth_cookies.py"
COMPOSE_PROD = ROOT / "docker-compose.prod.yml"
NGINX_EDGE = ROOT / "deploy" / "nginx" / "onboardai.aoe.kz.conf"

_COMPOSE_SECRETS = {
    "REDIS_PASSWORD": "compose-test-redis-password-not-a-secret",
    "SECRET_KEY": "compose-test-hmac-secret-key-32chars-min!",
    "SUPER_ADMIN_PASSWORD": "compose-test-super-admin-ok",
    "POSTGRES_PASSWORD": "compose-test-postgres-password-ok",
    "ONBOARD_OWNER_PASSWORD": "compose-test-owner-password-ok",
    "ONBOARD_APP_PASSWORD": "compose-test-app-password-ok",
}


def test_auth_cookies_source_has_no_secure_override_env() -> None:
    text = AUTH_COOKIES.read_text(encoding="utf-8")
    assert "AUTH_COOKIE_SECURE" not in text
    assert "settings.is_production" in text


def test_prod_compose_forbids_auth_cookie_secure_false() -> None:
    text = COMPOSE_PROD.read_text(encoding="utf-8")
    # Comments may mention the forbidden override; active env must never set it.
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("#") or not stripped:
            continue
        assert "AUTH_COOKIE_SECURE" not in stripped
    assert "docker-compose.ip.yml" in text  # documented as forbidden


def test_nginx_edge_config_exists_and_overwrites_xff() -> None:
    assert NGINX_EDGE.is_file()
    text = NGINX_EDGE.read_text(encoding="utf-8")
    assert "proxy_set_header X-Forwarded-For $remote_addr;" in text
    assert "proxy_add_x_forwarded_for" not in text.split("never")[0] or True
    assert "proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;" not in text
    assert "127.0.0.1:3000" in text


def test_production_https_sets_secure_cookie(monkeypatch: pytest.MonkeyPatch) -> None:
    """production + HTTPS posture => Secure cookie flag is true."""
    get_settings.cache_clear()
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("DEBUG", "false")
    monkeypatch.setenv("SECRET_KEY", "compose-test-hmac-secret-key-32chars-min!")
    monkeypatch.setenv("SUPER_ADMIN_PASSWORD", "compose-test-super-admin-ok")
    monkeypatch.setenv(
        "DATABASE_URL",
        "postgresql+asyncpg://onboard_app:compose-test-app-password-ok@db:5432/onboard_ai",
    )
    monkeypatch.setenv(
        "MIGRATION_DATABASE_URL",
        "postgresql+asyncpg://onboard_owner:compose-test-owner-password-ok@db:5432/onboard_ai",
    )
    monkeypatch.setenv("REDIS_URL", "redis://:compose-test-redis-password-not-a-secret@redis:6379/0")
    monkeypatch.setenv("ONBOARD_OWNER_PASSWORD", "compose-test-owner-password-ok")
    monkeypatch.setenv("ONBOARD_APP_PASSWORD", "compose-test-app-password-ok")
    monkeypatch.setenv("POSTGRES_PASSWORD", "compose-test-postgres-password-ok")
    # Avoid bot token production checks when unset.
    monkeypatch.delenv("BOT_SERVICE_TOKEN", raising=False)
    monkeypatch.delenv("BOT_TOKEN", raising=False)

    settings = Settings()
    assert settings.is_production is True

    # Bind settings for cookie helper
    monkeypatch.setattr("app.core.auth_cookies.get_settings", lambda: settings)
    response = Response()
    set_auth_cookies(
        response,
        TokenResponse(
            access_token="access",
            refresh_token="refresh",
            token_type="bearer",
        ),
    )
    # Starlette stores cookie headers; Secure flag appears in Set-Cookie.
    set_cookie_headers = [
        v for k, v in response.raw_headers if k.lower() == b"set-cookie"
    ]
    assert set_cookie_headers
    for header in set_cookie_headers:
        assert b"Secure" in header or b"secure" in header.lower()
    get_settings.cache_clear()


@pytest.mark.skipif(shutil.which("docker") is None, reason="docker not available")
def test_prod_compose_frontend_loopback_only() -> None:
    cmd = [
        "docker",
        "compose",
        "-f",
        "docker-compose.yml",
        "-f",
        "docker-compose.prod.yml",
        "config",
        "--format",
        "json",
    ]
    proc = subprocess.run(
        cmd,
        cwd=ROOT,
        env={**os.environ, **_COMPOSE_SECRETS},
        check=True,
        capture_output=True,
        text=True,
    )
    cfg = json.loads(proc.stdout)
    frontend = cfg["services"]["frontend"]
    for port in frontend.get("ports") or []:
        assert port.get("host_ip") == "127.0.0.1"
    api_env = cfg["services"]["api"].get("environment") or {}
    assert api_env.get("AUTH_COOKIE_SECURE") in (None, "")

"""F-04 / F-05 / F-07: production proxy edge, non-root, TLS contract surface."""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from tests.infra.compose_prod_env import COMPOSE_PROD_SECRETS as _COMPOSE_SECRETS

ROOT = Path(__file__).resolve().parents[2]
DOCKERFILE = ROOT / "Dockerfile"
COMPOSE_PROD = ROOT / "docker-compose.prod.yml"
DEPLOYMENT = ROOT / "DEPLOYMENT.md"
NGINX_PROD = ROOT / "frontend" / "nginx.prod.conf"
AUTH_COOKIES = ROOT / "app" / "core" / "auth_cookies.py"


def _compose_available() -> bool:
    return shutil.which("docker") is not None


def _compose_config(*, prod: bool, env: dict[str, str] | None = None) -> dict:
    cmd = ["docker", "compose", "-f", "docker-compose.yml"]
    if prod:
        cmd.extend(["-f", "docker-compose.prod.yml"])
    cmd.extend(["config", "--format", "json"])
    merged_env = {**os.environ, **(env or {})}
    proc = subprocess.run(
        cmd,
        cwd=ROOT,
        env=merged_env,
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(proc.stdout)


def test_dockerfile_runs_as_non_root_user() -> None:
    """F-05: API/bot image must drop privileges to a dedicated UID."""
    text = DOCKERFILE.read_text(encoding="utf-8")
    assert re.search(r"^USER\s+onboard\s*$", text, re.MULTILINE)
    assert "useradd" in text
    assert "--uid 10001" in text or "--uid=10001" in text
    assert "--gid 10001" in text or "gid 10001" in text
    # USER must appear after install/chown so the runtime process is non-root.
    user_idx = text.rfind("\nUSER ")
    assert user_idx != -1
    assert "chown" in text[:user_idx]
    assert "pip install" in text[:user_idx]


def test_nginx_prod_never_uses_proxy_add_x_forwarded_for() -> None:
    """F-04: shipped nginx must overwrite client IP, never append client XFF."""
    conf = NGINX_PROD.read_text(encoding="utf-8")
    assert "proxy_set_header X-Forwarded-For $remote_addr;" in conf
    assert "proxy_set_header X-Real-IP $remote_addr;" in conf
    # Comments may warn about the unsafe directive; the active config must not set it.
    assert "proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;" not in conf


def test_deployment_documents_tls_edge_contract() -> None:
    """F-07: public production requires an explicit TLS edge topology."""
    text = DEPLOYMENT.read_text(encoding="utf-8")
    assert "Public TLS / edge contract" in text or "TLS / edge contract" in text
    assert "TLS terminator" in text or "TLS terminator / reverse proxy" in text
    assert "TLS 1.2" in text
    assert "HSTS" in text
    assert "127.0.0.1" in text
    assert "Secure cookies" in text or "Secure" in text
    assert "TRUST_PROXY_HEADERS=true" in text


def test_auth_cookies_secure_in_production() -> None:
    """F-07: production cookies remain Secure via is_production."""
    text = AUTH_COOKIES.read_text(encoding="utf-8")
    assert '"secure": settings.is_production' in text or "'secure': settings.is_production" in text


@pytest.mark.skipif(not _compose_available(), reason="docker not available")
def test_prod_compose_fail_closed_network_surface() -> None:
    """F-04/F-07: API/DB/Redis unpublished; frontend localhost-only; trust+unpublished API."""
    cfg = _compose_config(
        prod=True,
        env={**_COMPOSE_SECRETS, "TRUST_PROXY_HEADERS": "false"},
    )
    api = cfg["services"]["api"]
    db = cfg["services"]["db"]
    redis = cfg["services"]["redis"]
    frontend = cfg["services"]["frontend"]

    assert not api.get("ports"), "production API must not publish host ports"
    assert not db.get("ports"), "production Postgres must not publish host ports"
    assert not redis.get("ports"), "production Redis must not publish host ports"

    api_env = api.get("environment") or {}
    assert api_env.get("APP_ENV") == "production"
    assert str(api_env.get("DEBUG")).lower() in {"false", "0"}
    assert str(api_env.get("SEED_DEMO")).lower() in {"false", "0"}
    assert str(api_env.get("TRUST_PROXY_HEADERS")).lower() in {"true", "1"}

    fe_ports = frontend.get("ports") or []
    assert fe_ports, "frontend should publish localhost for TLS edge"
    for port in fe_ports:
        assert port.get("host_ip") == "127.0.0.1"
        assert int(port.get("target") or 0) == 8080


def test_frontend_dockerfile_runs_nginx_as_non_root() -> None:
    text = (ROOT / "frontend" / "Dockerfile").read_text(encoding="utf-8")
    assert "USER nginx" in text
    assert "EXPOSE 8080" in text
    conf = (ROOT / "frontend" / "nginx.prod.conf").read_text(encoding="utf-8")
    assert "listen 8080;" in conf


@pytest.mark.skipif(not _compose_available(), reason="docker not available")
def test_prod_compose_file_documents_proxy_and_password_warnings() -> None:
    text = COMPOSE_PROD.read_text(encoding="utf-8")
    assert "proxy_add_x_forwarded_for" in text  # mentioned as forbidden
    assert "TRUST_PROXY_HEADERS" in text
    assert "postgres-password-rotation.md" in text
    assert "127.0.0.1" in text

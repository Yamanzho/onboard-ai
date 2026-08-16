"""Production nginx must not expose OpenAPI/Swagger/ReDoc (P0-05)."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from tests.infra.compose_prod_env import COMPOSE_PROD_SECRETS

ROOT = Path(__file__).resolve().parents[2]
FRONTEND = ROOT / "frontend"


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


def test_dev_nginx_proxies_openapi_docs() -> None:
    conf = (FRONTEND / "nginx.conf").read_text(encoding="utf-8")
    assert "proxy_pass http://api:8000/docs" in conf
    assert "proxy_pass http://api:8000/openapi.json" in conf
    assert "proxy_pass http://api:8000/redoc" in conf
    assert "location /api/" in conf
    assert "location = /health" in conf
    assert "location = /ready" in conf
    assert "proxy_pass http://api:8000/ready" in conf


def test_prod_nginx_overwrites_forwarded_for_with_remote_addr() -> None:
    """SEC-R1: trusted proxy must overwrite XFF, never append client-controlled values."""
    conf = (FRONTEND / "nginx.prod.conf").read_text(encoding="utf-8")
    assert "proxy_set_header X-Forwarded-For $remote_addr;" in conf
    assert "proxy_set_header X-Real-IP $remote_addr;" in conf
    assert "proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;" not in conf


def test_dev_nginx_overwrites_forwarded_for_with_remote_addr() -> None:
    """Keep dev nginx aligned with the SEC-R1 overwrite contract."""
    conf = (FRONTEND / "nginx.conf").read_text(encoding="utf-8")
    assert "proxy_set_header X-Forwarded-For $remote_addr;" in conf
    assert "proxy_set_header X-Real-IP $remote_addr;" in conf
    assert "proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;" not in conf


def test_deployment_md_host_nginx_example_overwrites_forwarded_for() -> None:
    """SEC-R1 docs residual: operator-facing example must not teach XFF append."""
    deployment = (ROOT / "DEPLOYMENT.md").read_text(encoding="utf-8")
    # Operator-facing nginx example must overwrite, not append.
    assert "proxy_set_header X-Forwarded-For $remote_addr;" in deployment
    assert "proxy_set_header X-Real-IP $remote_addr;" in deployment
    # No copy-pasteable unsafe directive in deployment docs (comments may warn).
    assert "proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;" not in deployment
    assert "TRUST_PROXY_HEADERS=true" in deployment
    assert "must not be done" in deployment or "must not" in deployment.lower()


def test_prod_nginx_blocks_openapi_docs() -> None:
    conf = (FRONTEND / "nginx.prod.conf").read_text(encoding="utf-8")
    assert "proxy_pass http://api:8000/docs" not in conf
    assert "proxy_pass http://api:8000/openapi.json" not in conf
    assert "proxy_pass http://api:8000/redoc" not in conf
    assert "location /docs" in conf
    assert "location /redoc" in conf
    assert "location = /openapi.json" in conf
    assert "return 404" in conf
    # API + health must remain proxied.
    assert "proxy_pass http://api:8000/api/" in conf
    assert "proxy_pass http://api:8000/health" in conf
    assert "proxy_pass http://api:8000/ready" in conf
    assert "location = /ready" in conf
    assert "proxy_set_header X-Forwarded-Proto $forwarded_proto;" in conf
    assert "map $http_x_forwarded_proto $forwarded_proto" in conf


def test_prod_nginx_has_restrictive_content_security_policy() -> None:
    """F-06: CSP present, not wildcard, scripts not unsafe-inline."""
    conf = (FRONTEND / "nginx.prod.conf").read_text(encoding="utf-8")
    assert "Content-Security-Policy" in conf
    # Extract the CSP header value.
    match = None
    for line in conf.splitlines():
        if "Content-Security-Policy" in line:
            match = line
            break
    assert match is not None
    assert "default-src 'self'" in match
    assert "script-src 'self'" in match
    assert "connect-src 'self'" in match
    assert "frame-ancestors 'none'" in match
    assert "object-src 'none'" in match
    assert "*" not in match.split("Content-Security-Policy", 1)[1]
    assert "script-src *" not in match
    assert "script-src 'unsafe-inline'" not in match
    assert "connect-src *" not in match


def test_dev_nginx_has_content_security_policy() -> None:
    conf = (FRONTEND / "nginx.conf").read_text(encoding="utf-8")
    assert "Content-Security-Policy" in conf
    assert "script-src 'self'" in conf
    assert "script-src 'unsafe-inline'" not in conf


def test_frontend_dockerfile_accepts_nginx_conf_arg() -> None:
    dockerfile = (FRONTEND / "Dockerfile").read_text(encoding="utf-8")
    assert "ARG NGINX_CONF=nginx.conf" in dockerfile
    assert "COPY ${NGINX_CONF}" in dockerfile or "COPY $NGINX_CONF" in dockerfile


@pytest.mark.skipif(not _compose_available(), reason="docker not available")
def test_prod_compose_uses_nginx_prod_conf() -> None:
    cfg = _compose_config(prod=True, env=COMPOSE_PROD_SECRETS)
    frontend = cfg["services"]["frontend"]
    build = frontend.get("build") or {}
    args = build.get("args") or {}
    assert args.get("NGINX_CONF") == "nginx.prod.conf"


@pytest.mark.skipif(not _compose_available(), reason="docker not available")
def test_dev_compose_does_not_force_nginx_prod_conf() -> None:
    cfg = _compose_config(prod=False, env={"APP_ENV": "development"})
    frontend = cfg["services"]["frontend"]
    build = frontend.get("build") or {}
    args = build.get("args") or {}
    assert args.get("NGINX_CONF") in (None, "nginx.conf")

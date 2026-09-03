"""HTTPS / DNS cutover preparation — static checks only.

Does not require live DNS, Certbot, or a production certificate.
"""

from __future__ import annotations

from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
NGINX_EDGE = ROOT / "deploy" / "nginx" / "onboardai.aoe.kz.conf"
NGINX_PROD = ROOT / "frontend" / "nginx.prod.conf"
HTTPS_DOC = ROOT / "docs" / "deployment" / "https.md"
ENV_EXAMPLE = ROOT / ".env.example"
MAIN_PY = ROOT / "app" / "main.py"
ENTRYPOINT = ROOT / "docker" / "entrypoint-api.sh"
AUTH_COOKIES = ROOT / "app" / "core" / "auth_cookies.py"

pytestmark = pytest.mark.security


def test_host_nginx_is_http_first_for_onboardai_hostname() -> None:
    text = NGINX_EDGE.read_text(encoding="utf-8")
    assert "server_name onboardai.aoe.kz;" in text
    assert "listen 80;" in text
    assert "listen 443" not in text
    assert "ssl_certificate" not in text
    assert "fullchain.pem" not in text
    assert "privkey.pem" not in text
    assert "location /.well-known/acme-challenge/" in text
    assert "proxy_pass http://127.0.0.1:3000;" in text
    assert "proxy_pass http://127.0.0.1:8000" not in text
    assert "proxy_http_version 1.1;" in text
    assert "proxy_read_timeout" in text
    assert "proxy_send_timeout" in text
    assert "proxy_set_header Host $host;" in text
    assert "proxy_set_header X-Real-IP $remote_addr;" in text
    assert "proxy_set_header X-Forwarded-For $remote_addr;" in text
    assert "proxy_set_header X-Forwarded-Proto $scheme;" in text
    assert "proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;" not in text
    assert "autoindex off;" in text
    assert "location ~ /\\.(git|env|ht)" in text
    assert "BEGIN RSA PRIVATE KEY" not in text
    assert "BEGIN PRIVATE KEY" not in text


def test_https_doc_has_manual_cutover_order() -> None:
    text = HTTPS_DOC.read_text(encoding="utf-8")
    assert "onboardai.aoe.kz" in text
    assert "185.146.1.22" in text
    assert "INVITE_BASE_URL=https://onboardai.aoe.kz" in text
    assert "sudo certbot --nginx -d onboardai.aoe.kz" in text
    assert "sudo certbot renew --dry-run" in text
    assert "dig +short onboardai.aoe.kz" in text
    assert "Not issued" in text or "not issued" in text
    assert "MANUAL" in text or "manual" in text


def test_env_example_documents_production_invite_base_url() -> None:
    text = ENV_EXAMPLE.read_text(encoding="utf-8")
    assert "INVITE_BASE_URL=http://localhost:3000" in text
    assert "INVITE_BASE_URL=https://onboardai.aoe.kz" in text
    assert "https://185.146.1.22" not in text
    assert "http://185.146.1.22" not in text


def test_application_code_has_no_hardcoded_production_ip_invite_url() -> None:
    needles = ("https://185.146.1.22", "http://185.146.1.22")
    hits: list[str] = []
    for pattern in ("app/**/*.py", "frontend/src/**/*.ts", "frontend/src/**/*.tsx"):
        for path in ROOT.glob(pattern):
            body = path.read_text(encoding="utf-8")
            if any(needle in body for needle in needles):
                hits.append(str(path.relative_to(ROOT)))
    assert hits == []


def test_fastapi_has_no_wildcard_cors_middleware() -> None:
    text = MAIN_PY.read_text(encoding="utf-8")
    assert "CORSMiddleware" not in text
    assert "allow_origins" not in text
    assert '["*"]' not in text


def _uvicorn_invocations(script: str) -> list[str]:
    """Join continued ``exec uvicorn`` commands into single logical lines."""
    invocations: list[str] = []
    pending: list[str] = []
    for raw in script.splitlines():
        line = raw.strip()
        if pending:
            pending.append(line.rstrip("\\").strip())
            if not raw.rstrip().endswith("\\"):
                invocations.append(" ".join(pending))
                pending = []
            continue
        if line.startswith("exec uvicorn"):
            pending = [line.rstrip("\\").strip()]
            if not raw.rstrip().endswith("\\"):
                invocations.append(" ".join(pending))
                pending = []
    return invocations


def test_production_entrypoint_enables_proxy_headers() -> None:
    script = ENTRYPOINT.read_text(encoding="utf-8")
    invocations = _uvicorn_invocations(script)
    production = [cmd for cmd in invocations if "--workers" in cmd]
    reload_cmds = [cmd for cmd in invocations if "--reload" in cmd]
    assert len(production) == 1
    assert len(reload_cmds) == 1
    assert "--proxy-headers" in production[0]
    assert "--forwarded-allow-ips=" in production[0]
    assert "--reload" not in production[0]
    assert "--proxy-headers" not in reload_cmds[0]
    assert "--forwarded-allow-ips=" not in reload_cmds[0]


def test_frontend_prod_nginx_passes_forwarded_proto() -> None:
    conf = NGINX_PROD.read_text(encoding="utf-8")
    assert "map $http_x_forwarded_proto $forwarded_proto" in conf
    assert "proxy_set_header X-Forwarded-Proto $forwarded_proto;" in conf
    assert "proxy_set_header X-Forwarded-For $remote_addr;" in conf
    assert "proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;" not in conf
    assert "location = /health" in conf
    assert "proxy_pass http://api:8000/health" in conf


def test_auth_cookies_remain_secure_in_production_without_samesite_change() -> None:
    text = AUTH_COOKIES.read_text(encoding="utf-8")
    assert '"secure": settings.is_production' in text
    assert '"samesite": "lax"' in text
    assert '"httponly": True' in text
    assert "AUTH_COOKIE_SECURE" not in text

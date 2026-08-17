"""Production compose immutability — no bind-mounts / no --reload (P0-04)."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


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


def _bind_mounts(service: dict) -> list[dict]:
    mounts: list[dict] = []
    for vol in service.get("volumes") or []:
        # Compose JSON: {"type": "bind", "source": "...", "target": "/app", ...}
        if isinstance(vol, dict) and vol.get("type") == "bind":
            mounts.append(vol)
        elif isinstance(vol, str) and ":/app" in vol:
            mounts.append({"raw": vol})
    return mounts


@pytest.mark.skipif(not _compose_available(), reason="docker not available")
def test_dev_compose_keeps_source_bind_mount_and_entrypoint() -> None:
    cfg = _compose_config(prod=False, env={"APP_ENV": "development"})
    api = cfg["services"]["api"]
    bot = cfg["services"]["bot"]

    api_binds = _bind_mounts(api)
    bot_binds = _bind_mounts(bot)
    assert api_binds, "dev API should bind-mount source for hot reload"
    assert bot_binds, "dev bot should bind-mount source for hot reload"
    assert any(str(m.get("target", "")) == "/app" or "/app" in str(m) for m in api_binds)
    assert any(str(m.get("target", "")) == "/app" or "/app" in str(m) for m in bot_binds)

    assert "entrypoint-api" in json.dumps(api.get("command"))
    assert "entrypoint-bot" in json.dumps(bot.get("command"))


@pytest.mark.skipif(not _compose_available(), reason="docker not available")
def test_prod_compose_has_no_source_bind_mounts() -> None:
    env = {
        "REDIS_PASSWORD": "compose-test-redis-password-not-a-secret",
        "SECRET_KEY": "compose-test-hmac-secret-key-32chars-min!",
        "SUPER_ADMIN_PASSWORD": "compose-test-super-admin-ok",
        "POSTGRES_PASSWORD": "compose-test-postgres-password-ok",
        "ONBOARD_OWNER_PASSWORD": "compose-test-owner-password-ok",
        "ONBOARD_APP_PASSWORD": "compose-test-app-password-ok",
    }
    cfg = _compose_config(prod=True, env=env)
    for name in ("api", "bot"):
        binds = _bind_mounts(cfg["services"][name])
        assert binds == [], f"production {name} must not bind-mount host source code"


@pytest.mark.skipif(not _compose_available(), reason="docker not available")
def test_prod_compose_forces_production_env_for_no_reload() -> None:
    env = {
        "REDIS_PASSWORD": "compose-test-redis-password-not-a-secret",
        "SECRET_KEY": "compose-test-hmac-secret-key-32chars-min!",
        "SUPER_ADMIN_PASSWORD": "compose-test-super-admin-ok",
        "POSTGRES_PASSWORD": "compose-test-postgres-password-ok",
        "ONBOARD_OWNER_PASSWORD": "compose-test-owner-password-ok",
        "ONBOARD_APP_PASSWORD": "compose-test-app-password-ok",
        # Ensure host .env cannot keep development / reload path.
        "APP_ENV": "development",
        "DEBUG": "true",
    }
    cfg = _compose_config(prod=True, env=env)
    api_env = cfg["services"]["api"].get("environment") or {}
    bot_env = cfg["services"]["bot"].get("environment") or {}

    assert api_env.get("APP_ENV") == "production"
    assert str(api_env.get("DEBUG")).lower() in {"false", "0"}
    assert bot_env.get("APP_ENV") == "production"
    assert str(bot_env.get("DEBUG")).lower() in {"false", "0"}

    # Named data volumes may remain; source binds must not.
    assert not cfg["services"]["api"].get("ports")
    assert not cfg["services"]["redis"].get("ports")
    assert not cfg["services"]["db"].get("ports")


def test_entrypoint_api_reload_only_outside_production() -> None:
    script = (ROOT / "docker" / "entrypoint-api.sh").read_text(encoding="utf-8")
    assert 'if [ "${APP_ENV_VALUE}" = "production" ]; then' in script
    assert "--workers" in script

    reload_lines = [
        line.strip()
        for line in script.splitlines()
        if "--reload" in line and not line.strip().startswith("#")
    ]
    assert len(reload_lines) == 1
    assert reload_lines[0].startswith("exec uvicorn")
    # Production branch must not mention --reload on the workers line.
    prod_block_start = script.index('if [ "${APP_ENV_VALUE}" = "production" ]; then')
    prod_block_end = script.index("fi", prod_block_start)
    prod_block = script[prod_block_start:prod_block_end]
    assert "--reload" not in prod_block
    assert "--workers" in prod_block
    assert "--proxy-headers" in prod_block
    assert "--forwarded-allow-ips=" in prod_block


def test_entrypoint_bot_has_no_reload() -> None:
    script = (ROOT / "docker" / "entrypoint-bot.sh").read_text(encoding="utf-8")
    assert "--reload" not in script
    assert "python -m app.bot" in script


def test_dockerfile_copies_application_into_image() -> None:
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    for path in ("COPY app ./app", "COPY docker ./docker", "COPY alembic ./alembic"):
        assert path in dockerfile
    assert "USER onboard" in dockerfile

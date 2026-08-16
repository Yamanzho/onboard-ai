"""Compose production Postgres password / networking surface (SEC-R2)."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from tests.infra.compose_prod_env import COMPOSE_PROD_SECRETS as _COMPOSE_SECRETS

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


@pytest.mark.skipif(not _compose_available(), reason="docker not available")
def test_dev_compose_keeps_localhost_postgres_with_default_password() -> None:
    # Isolate from a host POSTGRES_PASSWORD (e.g. leftover prod-test exports).
    cfg = _compose_config(prod=False, env={"POSTGRES_PASSWORD": ""})
    db = cfg["services"]["db"]
    ports = db.get("ports") or []
    assert ports, "dev Postgres should publish localhost port for tooling"
    assert any(p.get("host_ip") == "127.0.0.1" for p in ports)

    db_env = db.get("environment") or {}
    # Default development password remains available for local work.
    assert db_env.get("POSTGRES_PASSWORD") in {"onboard", "${POSTGRES_PASSWORD:-onboard}"} or (
        "onboard" in str(db_env.get("POSTGRES_PASSWORD", ""))
    )


@pytest.mark.skipif(not _compose_available(), reason="docker not available")
def test_prod_compose_requires_postgres_password_and_hides_ports() -> None:
    cfg = _compose_config(prod=True, env=_COMPOSE_SECRETS)
    api = cfg["services"]["api"]
    db = cfg["services"]["db"]

    assert not db.get("ports"), "production Postgres must not publish host ports"
    assert not api.get("ports"), "production API must not publish host ports"

    db_env = db.get("environment") or {}
    assert db_env.get("POSTGRES_PASSWORD") == _COMPOSE_SECRETS["POSTGRES_PASSWORD"]

    api_env = api.get("environment") or {}
    database_url = str(api_env.get("DATABASE_URL", ""))
    migration_url = str(api_env.get("MIGRATION_DATABASE_URL", ""))
    assert _COMPOSE_SECRETS["ONBOARD_APP_PASSWORD"] in database_url
    assert "onboard_app:" in database_url
    assert _COMPOSE_SECRETS["ONBOARD_OWNER_PASSWORD"] in migration_url
    assert "onboard_owner:" in migration_url
    # Must not retain the development default password in the rendered URL.
    assert "onboard:onboard@" not in database_url
    assert "onboard:onboard@" not in migration_url


@pytest.mark.skipif(not _compose_available(), reason="docker not available")
def test_prod_compose_fails_without_postgres_password() -> None:
    env = {**os.environ, **_COMPOSE_SECRETS}
    # Ensure compose interpolation does not pick a blank from the project .env
    # by forcing an empty value (Compose `:?` should still error on empty).
    env["POSTGRES_PASSWORD"] = ""
    cmd = [
        "docker",
        "compose",
        "-f",
        "docker-compose.yml",
        "-f",
        "docker-compose.prod.yml",
        "config",
    ]
    proc = subprocess.run(cmd, cwd=ROOT, env=env, capture_output=True, text=True)
    assert proc.returncode != 0
    combined = f"{proc.stdout}\n{proc.stderr}"
    assert "POSTGRES_PASSWORD" in combined


@pytest.mark.skipif(not _compose_available(), reason="docker not available")
def test_prod_compose_database_url_embeds_required_password() -> None:
    cfg = _compose_config(prod=True, env=_COMPOSE_SECRETS)
    api_env = cfg["services"]["api"].get("environment") or {}
    url = str(api_env.get("DATABASE_URL", ""))
    assert url.startswith("postgresql+asyncpg://")
    assert f":{_COMPOSE_SECRETS['ONBOARD_APP_PASSWORD']}@" in url
    assert "onboard_app:" in url
    assert "@db:5432/" in url
    mig = str(api_env.get("MIGRATION_DATABASE_URL", ""))
    assert "onboard_owner:" in mig
    assert f":{_COMPOSE_SECRETS['ONBOARD_OWNER_PASSWORD']}@" in mig


@pytest.mark.skipif(not _compose_available(), reason="docker not available")
def test_prod_compose_bot_database_url_not_localhost_inherited() -> None:
    """R-AUDIT-02: bot must not keep env_file localhost DATABASE_URL in prod render."""
    # Simulate a host .env that still points at localhost (common local default).
    env = {
        **_COMPOSE_SECRETS,
        "DATABASE_URL": "postgresql+asyncpg://onboard_app:compose-test-app-password-ok@localhost:5432/onboard_ai",
        "MIGRATION_DATABASE_URL": (
            "postgresql+asyncpg://onboard_owner:compose-test-owner-password-ok"
            "@localhost:5432/onboard_ai"
        ),
    }
    cfg = _compose_config(prod=True, env=env)
    bot_env = cfg["services"]["bot"].get("environment") or {}
    bot_db = str(bot_env.get("DATABASE_URL", ""))
    bot_mig = str(bot_env.get("MIGRATION_DATABASE_URL", ""))
    assert "onboard_app:" in bot_db
    assert "@db:5432/" in bot_db
    assert "@localhost:" not in bot_db
    assert "onboard_owner:" in bot_mig
    assert "@db:5432/" in bot_mig
    assert "@localhost:" not in bot_mig

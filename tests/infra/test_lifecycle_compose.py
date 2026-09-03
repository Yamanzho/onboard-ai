"""Phase 8C Compose/entrypoint contracts for drain, health, and migrations."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

from tests.infra.compose_prod_env import COMPOSE_PROD_SECRETS

pytestmark = pytest.mark.infra
ROOT = Path(__file__).resolve().parents[2]


def _compose_available() -> bool:
    return shutil.which("docker") is not None


def _compose_config(*, prod: bool) -> dict:
    cmd = ["docker", "compose", "-f", "docker-compose.yml"]
    if prod:
        cmd.extend(["-f", "docker-compose.prod.yml"])
    cmd.extend(["config", "--format", "json"])
    env = {**os.environ, **(COMPOSE_PROD_SECRETS if prod else {"APP_ENV": "development"})}
    proc = subprocess.run(
        cmd,
        cwd=ROOT,
        env=env,
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(proc.stdout)


def test_entrypoint_api_skips_migrations_when_flag_off() -> None:
    script = (ROOT / "docker" / "entrypoint-api.sh").read_text(encoding="utf-8")
    assert "ONBOARDAI_RUN_STARTUP_MIGRATIONS" in script
    assert "--timeout-graceful-shutdown" in script
    assert '"${SHUTDOWN_GRACE_SECONDS:-45}"' in script
    assert "8000/health" not in script


def test_entrypoint_migrate_runs_alembic_once() -> None:
    script = (ROOT / "docker" / "entrypoint-migrate.sh").read_text(encoding="utf-8")
    assert "bootstrap_rls_roles" in script
    assert "alembic upgrade head" in script
    assert "uvicorn" not in script
    assert "seed_demo" not in script


def test_dockerfile_installs_migrate_entrypoint() -> None:
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    assert "entrypoint-migrate.sh" in dockerfile


@pytest.mark.skipif(not _compose_available(), reason="docker not available")
def test_dev_and_prod_compose_separate_migrate_and_use_liveness_health() -> None:
    for prod in (False, True):
        cfg = _compose_config(prod=prod)
        services = cfg["services"]
        assert "migrate" in services
        api = services["api"]
        bot = services["bot"]
        frontend = services["frontend"]
        env = api.get("environment") or {}
        assert str(env.get("ONBOARDAI_RUN_STARTUP_MIGRATIONS")) == "0"
        depends = api.get("depends_on") or {}
        migrate_dep = depends.get("migrate") or {}
        assert migrate_dep.get("condition") == "service_completed_successfully"
        health = json.dumps(api.get("healthcheck") or {})
        assert "/health" in health
        assert "/ready" not in health
        assert api.get("stop_grace_period") in {60_000_000_000, "60s", "1m0s", 60}
        assert bot.get("stop_grace_period") in {60_000_000_000, "60s", "1m0s", 60}
        assert frontend.get("healthcheck")
        assert bot.get("healthcheck")
        migrate = services["migrate"]
        assert migrate.get("restart") in {None, "no", False, "disabled"}
        assert (migrate.get("environment") or {}).get("APP_ENV") == "development"


@pytest.mark.skipif(not _compose_available(), reason="docker not available")
def test_prod_migrate_has_no_source_bind_and_no_host_port() -> None:
    cfg = _compose_config(prod=True)
    migrate = cfg["services"]["migrate"]
    binds = [
        vol
        for vol in (migrate.get("volumes") or [])
        if isinstance(vol, dict) and vol.get("type") == "bind"
    ]
    assert binds == []
    assert not migrate.get("ports")

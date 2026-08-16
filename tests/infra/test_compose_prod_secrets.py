"""Compose production requires critical secrets at interpolate time (P0-02)."""

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


def _compose_config_unchecked(env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    cmd = [
        "docker",
        "compose",
        "-f",
        "docker-compose.yml",
        "-f",
        "docker-compose.prod.yml",
        "config",
    ]
    return subprocess.run(cmd, cwd=ROOT, env=env, capture_output=True, text=True)


@pytest.mark.skipif(not _compose_available(), reason="docker not available")
def test_prod_compose_passes_with_required_secrets() -> None:
    cfg = _compose_config(prod=True, env=_COMPOSE_SECRETS)
    api_env = cfg["services"]["api"].get("environment") or {}
    assert api_env.get("APP_ENV") == "production"
    assert str(api_env.get("DEBUG")).lower() in {"false", "0"}
    assert str(api_env.get("SEED_DEMO")).lower() in {"false", "0"}
    assert api_env.get("SECRET_KEY") == _COMPOSE_SECRETS["SECRET_KEY"]
    assert api_env.get("SUPER_ADMIN_PASSWORD") == _COMPOSE_SECRETS["SUPER_ADMIN_PASSWORD"]
    assert api_env.get("BOT_SERVICE_TOKEN") == _COMPOSE_SECRETS["BOT_SERVICE_TOKEN"]
    assert api_env.get("BOT_COMPANY_ID") == _COMPOSE_SECRETS["BOT_COMPANY_ID"]
    assert api_env.get("INVITE_BASE_URL") == _COMPOSE_SECRETS["INVITE_BASE_URL"]
    assert _COMPOSE_SECRETS["REDIS_PASSWORD"] in str(api_env.get("REDIS_URL", ""))


@pytest.mark.skipif(not _compose_available(), reason="docker not available")
@pytest.mark.parametrize(
    "missing_key",
    [
        "SECRET_KEY",
        "SUPER_ADMIN_PASSWORD",
        "REDIS_PASSWORD",
        "POSTGRES_PASSWORD",
        "ONBOARD_OWNER_PASSWORD",
        "ONBOARD_APP_PASSWORD",
        "BOT_SERVICE_TOKEN",
        "BOT_COMPANY_ID",
        "INVITE_BASE_URL",
    ],
)
def test_prod_compose_fails_when_critical_secret_missing(missing_key: str) -> None:
    env = {**os.environ, **_COMPOSE_SECRETS}
    env[missing_key] = ""
    proc = _compose_config_unchecked(env)
    assert proc.returncode != 0
    combined = f"{proc.stdout}\n{proc.stderr}"
    assert missing_key in combined


@pytest.mark.skipif(not _compose_available(), reason="docker not available")
def test_dev_compose_does_not_require_production_secrets() -> None:
    env = {**os.environ}
    for key in ("SECRET_KEY", "SUPER_ADMIN_PASSWORD", "REDIS_PASSWORD", "POSTGRES_PASSWORD"):
        env.pop(key, None)
        env[key] = ""
    # Dev compose must still render (secrets come from env_file / defaults at runtime).
    cfg = _compose_config(prod=False, env=env)
    assert "api" in cfg["services"]

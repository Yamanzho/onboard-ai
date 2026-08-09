"""Compose production networking / Redis auth surface (P0-03)."""

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
    # Avoid inheriting a host REDIS_PASSWORD that could mask missing-password failures.
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
def test_dev_compose_keeps_localhost_redis_without_requirepass() -> None:
    cfg = _compose_config(prod=False)
    redis = cfg["services"]["redis"]
    ports = redis.get("ports") or []
    assert ports, "dev Redis should publish localhost port for tooling"
    assert all(
        str(p.get("host_ip") or "0.0.0.0") in {"127.0.0.1", "localhost"}
        or str(p.get("published", "")).startswith("127.")
        for p in ports
    ) or any(p.get("host_ip") == "127.0.0.1" for p in ports)
    # No requirepass in default command (image default redis-server).
    command = redis.get("command")
    assert command is None or "requirepass" not in json.dumps(command)


@pytest.mark.skipif(not _compose_available(), reason="docker not available")
def test_prod_compose_requires_redis_password_and_hides_ports() -> None:
    env = {
        "REDIS_PASSWORD": "compose-test-redis-password-not-a-secret",
        "SECRET_KEY": "compose-test-hmac-secret-key-32chars-min!",
        "SUPER_ADMIN_PASSWORD": "compose-test-super-admin-ok",
        "POSTGRES_PASSWORD": "compose-test-postgres-password-ok",
        "ONBOARD_OWNER_PASSWORD": "compose-test-owner-password-ok",
        "ONBOARD_APP_PASSWORD": "compose-test-app-password-ok",
    }
    cfg = _compose_config(prod=True, env=env)
    api = cfg["services"]["api"]
    bot = cfg["services"]["bot"]
    redis = cfg["services"]["redis"]
    frontend = cfg["services"]["frontend"]

    assert not api.get("ports"), "production API must not publish host ports"
    assert not redis.get("ports"), "production Redis must not publish host ports"

    bot_ports = bot.get("ports") or []
    assert len(bot_ports) == 1
    assert bot_ports[0].get("host_ip") == "127.0.0.1"

    assert frontend.get("ports"), "frontend remains the public edge"

    redis_cmd = redis.get("command")
    assert redis_cmd is not None
    assert "requirepass" in json.dumps(redis_cmd)

    api_env = api.get("environment") or {}
    bot_env = bot.get("environment") or {}
    assert "compose-test-redis-password-not-a-secret" in str(api_env.get("REDIS_URL", ""))
    assert "compose-test-redis-password-not-a-secret" in str(bot_env.get("REDIS_URL", ""))


@pytest.mark.skipif(not _compose_available(), reason="docker not available")
def test_prod_compose_fails_without_redis_password() -> None:
    env = {**os.environ}
    env["SECRET_KEY"] = "compose-test-hmac-secret-key-32chars-min!"
    env["SUPER_ADMIN_PASSWORD"] = "compose-test-super-admin-ok"
    env["POSTGRES_PASSWORD"] = "compose-test-postgres-password-ok"
    env.pop("REDIS_PASSWORD", None)
    # Ensure compose interpolation does not pick a blank from the project .env
    # by forcing an empty value (Compose `:?` should still error on empty).
    env["REDIS_PASSWORD"] = ""
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
    assert "REDIS_PASSWORD" in combined

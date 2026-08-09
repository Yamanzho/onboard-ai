"""Optional Docker smoke: Redis requirepass + rate-limit client (P0-03)."""

from __future__ import annotations

import shutil
import subprocess
import time
import uuid

import pytest

REDIS_IMAGE = "redis:7-alpine"


def _docker_available() -> bool:
    if shutil.which("docker") is None:
        return False
    proc = subprocess.run(
        ["docker", "info"],
        capture_output=True,
        check=False,
    )
    return proc.returncode == 0


@pytest.mark.skipif(not _docker_available(), reason="docker daemon not available")
def test_redis_requirepass_rejects_anonymous_and_accepts_password() -> None:
    name = f"onboard-redis-auth-{uuid.uuid4().hex[:8]}"
    password = f"test-pass-{uuid.uuid4().hex}"
    port = "16379"
    try:
        subprocess.run(
            [
                "docker",
                "run",
                "-d",
                "--rm",
                "--name",
                name,
                "-p",
                f"127.0.0.1:{port}:6379",
                REDIS_IMAGE,
                "redis-server",
                "--requirepass",
                password,
            ],
            check=True,
            capture_output=True,
            text=True,
        )
        # Wait until Redis answers AUTH.
        deadline = time.time() + 15
        while time.time() < deadline:
            probe = subprocess.run(
                [
                    "docker",
                    "exec",
                    "-e",
                    f"REDISCLI_AUTH={password}",
                    name,
                    "redis-cli",
                    "ping",
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            if probe.returncode == 0 and "PONG" in probe.stdout:
                break
            time.sleep(0.25)
        else:
            pytest.fail("Redis with requirepass did not become ready")

        anon = subprocess.run(
            ["docker", "exec", name, "redis-cli", "ping"],
            capture_output=True,
            text=True,
            check=False,
        )
        assert anon.returncode != 0 or "NOAUTH" in (anon.stdout + anon.stderr)
        assert "PONG" not in anon.stdout

        from redis import Redis

        with pytest.raises(Exception):
            bad = Redis.from_url(f"redis://127.0.0.1:{port}/0", decode_responses=True)
            try:
                bad.ping()
            finally:
                bad.close()

        good = Redis.from_url(
            f"redis://:{password}@127.0.0.1:{port}/0",
            decode_responses=True,
        )
        try:
            assert good.ping() is True
            # Rate-limiter style INCR works with authenticated URL.
            key = f"rate_limit:smoke:{uuid.uuid4().hex}"
            assert int(good.incr(key)) == 1
            good.expire(key, 30)
        finally:
            good.close()
    finally:
        subprocess.run(["docker", "rm", "-f", name], capture_output=True, check=False)

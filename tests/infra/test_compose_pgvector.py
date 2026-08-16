"""Compose Postgres image must ship pgvector without a second vector database."""

from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


def _compose_available() -> bool:
    return shutil.which("docker") is not None


@pytest.mark.skipif(not _compose_available(), reason="docker not available")
def test_dev_compose_uses_pgvector_postgres_image() -> None:
    proc = subprocess.run(
        ["docker", "compose", "-f", "docker-compose.yml", "config", "--format", "json"],
        cwd=ROOT,
        env={**os.environ, "POSTGRES_PASSWORD": ""},
        check=True,
        capture_output=True,
        text=True,
    )
    import json

    cfg = json.loads(proc.stdout)
    image = str(cfg["services"]["db"].get("image", ""))
    assert "pgvector/pgvector" in image
    assert "pg16" in image
    assert "postgres:16-alpine" not in image

"""F-03: PostgreSQL volume password rotation runbook must exist and be safe."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RUNBOOK = ROOT / "docs" / "runbooks" / "postgres-password-rotation.md"
DEPLOYMENT = ROOT / "DEPLOYMENT.md"
COMPOSE_PROD = ROOT / "docker-compose.prod.yml"
ENV_EXAMPLE = ROOT / ".env.example"


def test_postgres_password_rotation_runbook_exists() -> None:
    assert RUNBOOK.is_file(), "F-03 runbook missing"
    text = RUNBOOK.read_text(encoding="utf-8")
    assert "POSTGRES_PASSWORD" in text
    assert "existing" in text.lower() or "already initialized" in text.lower()
    assert "ALTER ROLE" in text or r"\password" in text
    assert "onboard_app" in text
    assert "onboard_owner" in text
    assert "backup" in text.lower()
    assert "rollback" in text.lower()
    # Must warn that .env edit alone is not rotation on an existing volume.
    assert "does **not** rotate" in text or "does not rotate" in text.lower()
    # Must not recommend deleting the production volume as the primary rotation method.
    assert "Do **not** delete the production" in text or "do not delete the production" in text.lower()
    assert "Not allowed as the primary procedure" in text or "not allowed as the primary" in text.lower()
    assert "down -v" in text


def test_deployment_and_compose_warn_about_postgres_password_volume() -> None:
    deployment = DEPLOYMENT.read_text(encoding="utf-8")
    compose = COMPOSE_PROD.read_text(encoding="utf-8")
    env_example = ENV_EXAMPLE.read_text(encoding="utf-8")

    assert "postgres-password-rotation.md" in deployment
    assert "does **not** rotate" in deployment or "does not rotate" in deployment.lower()

    assert "F-03" in compose or "does NOT rotate" in compose or "first init" in compose
    assert "postgres-password-rotation.md" in compose

    assert "F-03" in env_example
    assert "does NOT rotate" in env_example or "does not rotate" in env_example.lower()
    assert "postgres-password-rotation.md" in env_example

"""CI workflow must exist and cover backend, frontend, security, and compose."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "ci.yml"


def test_github_actions_ci_workflow_exists() -> None:
    assert WORKFLOW.is_file()
    text = WORKFLOW.read_text(encoding="utf-8")
    for needle in (
        "pytest",
        "-m security",
        "alembic",
        "ruff",
        "npm ci",
        "npm run lint",
        "npm run typecheck",
        "npm run build",
        "docker compose",
        "docker-compose.prod.yml",
        "docker build",
        "COMPOSE_PROD",
        "SECRET_KEY",
        "bootstrap_rls_roles",
        "pgvector/pgvector",
    ):
        assert needle in text, f"CI workflow missing {needle!r}"
    # Dummy CI secrets only — never require live production credentials.
    assert "from-vault" not in text.lower()
    assert "github.secrets.SUPER_ADMIN_PASSWORD" not in text
    assert "ONBOARDAI_AI7_LIVE_OPENAI" not in text
    assert "evaluate_kb_retrieval" not in text
    assert "evaluate_rag" not in text
    assert "OPENAI_API_KEY" not in text
    assert "AI_EMBEDDING_API_KEY" not in text

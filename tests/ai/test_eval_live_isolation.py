"""AI-8 live OpenAI evaluation must stay opt-in and isolated from CI/pytest."""

from __future__ import annotations

from pathlib import Path

import pytest

from app.core.exceptions import ValidationError
from app.services.ai.evaluation import (
    LIVE_OPENAI_ENV,
    eval_cache_path,
    live_openai_enabled,
)

ROOT = Path(__file__).resolve().parents[2]


def test_live_openai_defaults_off(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(LIVE_OPENAI_ENV, raising=False)
    assert live_openai_enabled() is False


def test_ci_workflow_never_runs_live_openai() -> None:
    text = (ROOT / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")
    assert "ONBOARDAI_AI7_LIVE_OPENAI" not in text
    assert "evaluate_kb_retrieval" not in text
    assert "evaluate_rag" not in text
    assert "OPENAI_API_KEY" not in text
    assert "AI_EMBEDDING_API_KEY" not in text


def test_app_startup_does_not_import_evaluation() -> None:
    text = (ROOT / "app" / "main.py").read_text(encoding="utf-8")
    assert "evaluate_kb_retrieval" not in text
    assert "eval_runner" not in text
    assert "rag_eval" not in text
    assert "LIVE_OPENAI" not in text
    assert "eval_corpus" not in text


def test_eval_cache_is_gitignored_and_model_specific() -> None:
    gitignore = (ROOT / ".gitignore").read_text(encoding="utf-8")
    assert ".ai7_embedding_cache/" in gitignore
    fake = eval_cache_path(ROOT, "fake")
    openai = eval_cache_path(ROOT, "text-embedding-3-small")
    assert fake != openai
    assert fake.parent == ROOT / ".ai7_embedding_cache"
    assert openai.name == "text-embedding-3-small.json"
    assert fake.parent == openai.parent


def test_pytest_conftest_forces_fake_embeddings() -> None:
    text = (ROOT / "tests" / "conftest.py").read_text(encoding="utf-8")
    assert 'ai_embedding_provider = "fake"' in text


def test_live_provider_requires_env_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(LIVE_OPENAI_ENV, raising=False)
    from scripts.evaluate_kb_retrieval import _provider
    from scripts.evaluate_rag import _providers

    with pytest.raises(ValidationError, match="LIVE_OPENAI"):
        _provider(live_openai=True)
    with pytest.raises(ValidationError, match="LIVE_OPENAI"):
        _providers(live_openai=True)

"""AI-10A must not weaken ACL, tenant isolation, or secret handling."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_ai10a_does_not_add_acl_or_tenant_selectors() -> None:
    api = (ROOT / "app" / "api" / "v1" / "ai.py").read_text(encoding="utf-8")
    schema = (ROOT / "app" / "schemas" / "ai.py").read_text(encoding="utf-8")
    telegram = (ROOT / "app" / "bot" / "handlers" / "ai.py").read_text(
        encoding="utf-8"
    ) + (ROOT / "app" / "bot" / "services" / "ai_client.py").read_text(encoding="utf-8")
    chat = (ROOT / "app" / "services" / "ai" / "chat.py").read_text(encoding="utf-8")
    for src in (api, telegram, chat):
        assert "AIACLService" not in src
        assert "VectorACL" not in src
        assert "AIConversation" not in src
        assert "openai.com" not in src
    request_block = schema.split("class AIChatRequest", 1)[1].split("class AIChatCitation", 1)[0]
    for field in ("company_id", "employee_id", "tenant_id", "role", "top_k", "min_score", "model", "provider"):
        assert f"    {field}:" not in request_block
    assert "ArticleService" not in api
    assert "list_articles" not in api


def test_ai10a_eval_cache_is_not_production_path() -> None:
    production = "\n".join(
        path.read_text(encoding="utf-8")
        for path in (
            ROOT / "app" / "services" / "ai" / "chat.py",
            ROOT / "app" / "api" / "v1" / "ai.py",
            ROOT / "app" / "bot" / "handlers" / "ai.py",
            ROOT / "app" / "bot" / "services" / "ai_client.py",
        )
    )
    assert ".ai7_embedding_cache" not in production
    assert "eval_cache_path" not in production

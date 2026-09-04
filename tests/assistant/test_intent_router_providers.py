"""Phase 9I IntentRouter stays provider-neutral across Phase 9J adapters."""

from __future__ import annotations

from typing import Any

import pytest

from app.core.ai_constants import INTENT_CLASSIFIER_MARKER
from app.db.enums import AssistantIntent
from app.services.ai.anthropic_llm import AnthropicLLMProvider
from app.services.ai.gemini_llm import GeminiLLMProvider
from app.services.ai.openai_compatible_llm import OpenAICompatibleLLMProvider
from app.services.ai.openai_llm import OpenAILLMProvider
from app.services.assistant.intent_router import IntentRouter

CLASSIFIER_TEXT = '{"intent":"help","confidence":0.91,"topic_hint":""}'
AMBIGUOUS = "xyzzy plugh classify this please"


def _openai_body(text: str) -> dict[str, Any]:
    return {"choices": [{"message": {"content": text}}]}


def _anthropic_body(text: str) -> dict[str, Any]:
    return {"content": [{"type": "text", "text": text}]}


def _gemini_body(text: str) -> dict[str, Any]:
    return {"candidates": [{"content": {"parts": [{"text": text}]}}]}


@pytest.mark.parametrize(
    ("provider_factory", "response_body"),
    [
        (
            lambda post: OpenAILLMProvider(
                api_key="secret-openai-123", http_post=post
            ),
            _openai_body,
        ),
        (
            lambda post: AnthropicLLMProvider(
                api_key="secret-anthropic-123",
                model="claude-test",
                http_post=post,
            ),
            _anthropic_body,
        ),
        (
            lambda post: GeminiLLMProvider(
                api_key="secret-gemini-123",
                model="gemini-test",
                http_post=post,
            ),
            _gemini_body,
        ),
        (
            lambda post: OpenAICompatibleLLMProvider(
                api_key="secret-qwen-123",
                model="qwen-test",
                base_url="https://example.test/compatible-mode/v1",
                http_post=post,
            ),
            _openai_body,
        ),
    ],
)
@pytest.mark.asyncio
async def test_intent_classifier_contract_is_provider_neutral(
    provider_factory: object,
    response_body: object,
) -> None:
    seen: dict[str, str] = {}

    async def post(
        _url: str, _headers: dict[str, str], payload: dict[str, Any]
    ) -> dict[str, Any]:
        if "system_instruction" in payload:
            seen["system"] = payload["system_instruction"]["parts"][0]["text"]
            seen["user"] = payload["contents"][0]["parts"][0]["text"]
        elif isinstance(payload.get("system"), str):
            seen["system"] = payload["system"]
            seen["user"] = payload["messages"][0]["content"]
        else:
            seen["system"] = payload["messages"][0]["content"]
            seen["user"] = payload["messages"][1]["content"]
        return response_body(CLASSIFIER_TEXT)  # type: ignore[operator]

    provider = provider_factory(post)  # type: ignore[operator]
    router = IntentRouter(llm_provider=provider)
    routed = await router.route(AMBIGUOUS)
    assert routed.intent is AssistantIntent.HELP
    assert routed.used_llm is True
    assert routed.source == "llm"
    assert INTENT_CLASSIFIER_MARKER in seen["system"]
    assert seen["user"] == AMBIGUOUS


def test_chat_and_orchestrator_have_no_provider_branches() -> None:
    from pathlib import Path

    root = Path(__file__).resolve().parents[2]
    paths = [
        root / "app" / "services" / "ai" / "chat.py",
        root / "app" / "services" / "assistant" / "orchestrator.py",
        root / "app" / "services" / "assistant" / "intent_router.py",
    ]
    forbidden = (
        "AnthropicLLMProvider",
        "GeminiLLMProvider",
        "OpenAICompatibleLLMProvider",
        "api.anthropic.com",
        "generativelanguage.googleapis.com",
        "openai_compatible",
        "qwen",
    )
    for path in paths:
        text = path.read_text(encoding="utf-8")
        for needle in forbidden:
            assert needle not in text, f"{path.name} must not mention {needle!r}"

"""AI-12B frontend history — static contract and security checks."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FRONTEND_SRC = ROOT / "frontend" / "src"


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_history_endpoints_exist_without_tenant_selectors() -> None:
    api = _read(FRONTEND_SRC / "services" / "aiApi.ts")
    assert "listAIConversations" in api
    assert "getAIConversation" in api
    assert "deleteAIConversation" in api
    assert "/api/v1/ai/conversations" in api
    assert "method: 'DELETE'" in api
    for forbidden in (
        "company_id",
        "employee_id",
        "tenant_id",
        "user_id",
        "actor_role",
        "top_k",
        "min_score",
        "model",
        "provider",
        "openai.com",
        "localStorage",
        "Authorization",
    ):
        assert forbidden not in api


def test_history_selection_and_restore() -> None:
    chat = _read(FRONTEND_SRC / "components" / "ai" / "AIChat.tsx")
    assert "AIConversationHistory" in chat
    assert "selectConversation" in chat
    assert "getAIConversation" in chat
    assert "mapServerMessages" in chat
    assert "searchParams.get('c')" in chat
    assert "listQuery.data?.items[0]" in chat
    assert "setSearchParams({ c: first.conversation_id }" in chat


def test_new_chat_does_not_delete_history() -> None:
    chat = _read(FRONTEND_SRC / "components" / "ai" / "AIChat.tsx")
    start = chat.split("function startNewChat", 1)[1].split(
        "function selectConversation", 1
    )[0]
    assert "setStartedNewChat(true)" in start
    assert "deleteAIConversation" not in start
    assert "deleteMutation.mutate" not in start
    assert "setSearchParams({}, { replace: true })" in start


def test_follow_up_reuses_conversation_id() -> None:
    chat = _read(FRONTEND_SRC / "components" / "ai" / "AIChat.tsx")
    assert "mutation.mutate({ message, conversationId })" in chat
    api = _read(FRONTEND_SRC / "services" / "aiApi.ts")
    assert "{ message, conversation_id: conversationId }" in api


def test_no_streaming_or_secrets() -> None:
    src = (
        _read(FRONTEND_SRC / "components" / "ai" / "AIChat.tsx")
        + _read(FRONTEND_SRC / "components" / "ai" / "AIConversationHistory.tsx")
        + _read(FRONTEND_SRC / "services" / "aiApi.ts")
    )
    for needle in (
        "EventSource",
        "WebSocket",
        "text/event-stream",
        "openai.com",
        "OPENAI_API_KEY",
        "dangerouslySetInnerHTML",
        "localStorage",
    ):
        assert needle not in src

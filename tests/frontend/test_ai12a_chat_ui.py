"""AI-12A Employee AI Chat UI — static contract and security checks.

There is no frontend unit-test runner in this repo. These tests inspect
source so CI still guards the HTTP body, route, and XSS/auth invariants.
"""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FRONTEND_SRC = ROOT / "frontend" / "src"

AI_FILES = [
    FRONTEND_SRC / "types" / "ai.ts",
    FRONTEND_SRC / "services" / "aiApi.ts",
    FRONTEND_SRC / "lib" / "aiChatErrors.ts",
    FRONTEND_SRC / "components" / "ai" / "AIChat.tsx",
    FRONTEND_SRC / "components" / "ai" / "AIComposer.tsx",
    FRONTEND_SRC / "components" / "ai" / "AIConversationHistory.tsx",
    FRONTEND_SRC / "pages" / "employee" / "EmployeeAIPage.tsx",
]


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _ai_src() -> str:
    return "\n".join(_read(path) for path in AI_FILES)


def test_ai_route_redirects_and_navigation_hidden() -> None:
    routes = _read(FRONTEND_SRC / "routes" / "AppRoutes.tsx")
    nav = _read(FRONTEND_SRC / "lib" / "navigation.ts")
    i18n = _read(FRONTEND_SRC / "i18n" / "ru.ts")
    assert 'path="ai"' in routes
    assert 'Navigate to="/employee" replace' in routes
    assert "EmployeeAIPage" not in routes
    assert "RequireRole allowed={['employee']}" in routes
    assert "workspacePath('employee', '/ai')" not in nav
    assert "nav.aiAssistant" not in nav
    assert "aiAssistant: 'AI Ассистент'" in i18n
    assert "emptyDescription: 'Задайте вопрос по внутренним материалам компании.'" in i18n


def test_ai_route_is_employee_workspace_only() -> None:
    routes = _read(FRONTEND_SRC / "routes" / "AppRoutes.tsx")
    nav = _read(FRONTEND_SRC / "lib" / "navigation.ts")
    employee_block = routes.split('workspace="employee"')[1].split(
        "workspace="
    )[0]
    assert 'path="ai"' in employee_block
    assert 'Navigate to="/employee" replace' in employee_block
    assert "EmployeeAIPage" not in employee_block
    company_nav = nav.split("export const COMPANY_NAV")[1].split(
        "export const HR_NAV"
    )[0]
    hr_nav = nav.split("export const HR_NAV")[1].split(
        "export const EMPLOYEE_NAV"
    )[0]
    platform_nav = nav.split("export const PLATFORM_NAV")[1].split(
        "const NAV_BY_WORKSPACE"
    )[0]
    employee_nav = nav.split("export const EMPLOYEE_NAV")[1].split(
        "export const PLATFORM_NAV"
    )[0]
    assert "/ai" not in company_nav
    assert "/ai" not in hr_nav
    assert "/ai" not in platform_nav
    assert "/ai" not in employee_nav


def test_first_request_omits_conversation_id() -> None:
    api = _read(FRONTEND_SRC / "services" / "aiApi.ts")
    assert "conversationId" in api
    assert "{ message, conversation_id: conversationId }" in api
    assert "{ message }" in api
    assert "conversationId\n    ? { message, conversation_id: conversationId }\n    : { message }" in api


def test_request_body_has_no_tenant_selectors() -> None:
    api = _read(FRONTEND_SRC / "services" / "aiApi.ts")
    for forbidden in (
        "company_id",
        "employee_id",
        "tenant_id",
        "user_id",
        "actor_role",
        "role",
        "top_k",
        "min_score",
        "model",
        "provider",
    ):
        assert forbidden not in api, f"AI request must not include {forbidden}"


def test_reuses_authenticated_api_client() -> None:
    api = _read(FRONTEND_SRC / "services" / "aiApi.ts")
    assert "from './apiClient'" in api
    assert "apiRequest<AIChatResponse>('/api/v1/ai/chat'" in api
    assert "method: 'POST'" in api
    assert "fetch(" not in api
    assert "Authorization" not in api
    assert "localStorage" not in api


def test_conversation_id_is_client_state_only() -> None:
    chat = _read(FRONTEND_SRC / "components" / "ai" / "AIChat.tsx")
    assert "searchParams.get('c')" in chat
    assert "setSearchParams({ c: data.conversation_id }" in chat
    assert "localStorage" not in chat
    assert "sessionStorage" not in chat


def test_new_chat_clears_local_state_without_backend_delete() -> None:
    chat = _read(FRONTEND_SRC / "components" / "ai" / "AIChat.tsx")
    assert "function startNewChat" in chat
    assert "setMessages([])" in chat
    assert "setSearchParams({}, { replace: true })" in chat
    assert "setError(null)" in chat
    start = chat.split("function startNewChat", 1)[1].split("function selectConversation", 1)[0]
    assert "deleteAIConversation" not in start
    assert "deleteMutation.mutate" not in start


def test_citations_render_titles_not_internal_ids() -> None:
    chat = _read(FRONTEND_SRC / "components" / "ai" / "AIChat.tsx")
    assert "{citation.title}" in chat
    assert "citation.source_id" not in chat
    assert "source_id}" not in chat
    assert "paths.article(citation.article_id)" in chat
    assert "visibleAssistantText" in chat
    assert r"\[S\d+\]" in chat


def test_no_answer_and_empty_citations() -> None:
    chat = _read(FRONTEND_SRC / "components" / "ai" / "AIChat.tsx")
    assert "noAnswer: data.no_answer" in chat
    assert "message.citations.length > 0" in chat
    assert "items.length === 0) return null" in chat


def test_loading_and_duplicate_submit_guard() -> None:
    chat = _read(FRONTEND_SRC / "components" / "ai" / "AIChat.tsx")
    composer = _read(FRONTEND_SRC / "components" / "ai" / "AIComposer.tsx")
    assert "retry: false" in chat
    assert "if (!message || pending || restoring) return" in chat
    assert "disabled={pending}" in chat
    assert "disabled={!canSend}" in composer
    assert "disabled={disabled}" in composer


def test_empty_message_and_char_limit() -> None:
    chat = _read(FRONTEND_SRC / "components" / "ai" / "AIChat.tsx")
    composer = _read(FRONTEND_SRC / "components" / "ai" / "AIComposer.tsx")
    types = _read(FRONTEND_SRC / "types" / "ai.ts")
    assert "MAX_CHAT_QUESTION_CHARS = 2000" in types
    assert "maxLength={MAX_CHAT_QUESTION_CHARS}" in composer
    assert "message.length > MAX_CHAT_QUESTION_CHARS" in chat
    assert "raw.trim()" in chat
    assert "value.trim().length > 0" in composer


def test_error_mapping_is_safe() -> None:
    errors = _read(FRONTEND_SRC / "lib" / "aiChatErrors.ts")
    i18n = _read(FRONTEND_SRC / "i18n" / "ru.ts")
    assert "case 401:" in errors
    assert "case 403:" in errors
    assert "case 400:" in errors
    assert "case 422:" in errors
    assert "case 429:" in errors
    assert "case 503:" in errors
    assert "error.detail" not in errors
    assert "error.message" not in errors
    assert "У вас нет доступа к AI Assistant." in i18n
    assert "Слишком много запросов. Попробуйте позже." in i18n
    assert "AI Assistant временно недоступен. Попробуйте позже." in i18n
    assert "Не удалось получить ответ. Попробуйте ещё раз." in i18n
    assert "retryAfterSeconds" in errors


def test_no_secrets_openai_or_datastore_in_frontend_ai() -> None:
    src = _ai_src()
    for needle in (
        "OPENAI_API_KEY",
        "openai.com",
        "AI_LLM_API_KEY",
        "AI_EMBEDDING_API_KEY",
        "BOT_SERVICE_TOKEN",
        "pgvector",
        "postgres://",
        "redis://",
        "dangerouslySetInnerHTML",
        "EventSource",
        "WebSocket",
        "text/event-stream",
    ):
        assert needle.lower() not in src.lower(), f"forbidden pattern {needle!r}"


def test_plain_text_rendering() -> None:
    chat = _read(FRONTEND_SRC / "components" / "ai" / "AIChat.tsx")
    assert "whitespace-pre-wrap" in chat
    assert "dangerouslySetInnerHTML" not in chat


def test_empty_state_suggestions_are_ui_shortcuts() -> None:
    chat = _read(FRONTEND_SRC / "components" / "ai" / "AIChat.tsx")
    i18n = _read(FRONTEND_SRC / "i18n" / "ru.ts")
    assert "EmptyState" in chat
    assert "onPick={(prompt) => sendMessage(prompt)}" in chat
    assert "Как получить доступ к VPN?" in i18n
    assert "Где найти правила отпуска?" in i18n
    assert "К кому обратиться по IT-проблемам?" in i18n


def test_keyboard_enter_send_shift_newline() -> None:
    composer = _read(FRONTEND_SRC / "components" / "ai" / "AIComposer.tsx")
    assert "event.key !== 'Enter'" in composer
    assert "event.shiftKey" in composer
    assert "isCoarsePointer" in composer
    assert "event.preventDefault()" in composer

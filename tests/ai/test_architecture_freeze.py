"""AI-0 architecture freeze document must keep the approved security rules."""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ARCHITECTURE = ROOT / "docs" / "ai" / "architecture.md"
EVAL_REPORT = ROOT / "docs" / "ai" / "ai7-retrieval-evaluation.md"
EVAL_REPORT_AI8 = ROOT / "docs" / "ai" / "ai8-real-retrieval-evaluation.md"


def test_architecture_freeze_document_exists() -> None:
    assert ARCHITECTURE.is_file()
    text = ARCHITECTURE.read_text(encoding="utf-8")
    for needle in (
        "PostgreSQL",
        "pgvector",
        "published",
        "ACL-first",
        "ArticleService",
        "retrieval acceleration",
        "Telegram",
        "REST",
        "FSM",
        "not a KB source",
        "no-answer",
        "Citations are mandatory",
        "RLS",
        "Super Admin",
        "impersonation",
        "Qdrant",
        "Weaviate",
        "Pinecone",
        "FakeEmbeddingProvider",
        "AUTH",
        "PROGRAM ACL",
        "LLM",
    ):
        assert needle in text, f"architecture freeze missing {needle!r}"
    assert "Vector storage is a retrieval acceleration layer" in text
    assert "knowledge_article_chunks" in text
    assert "after commit" in text.lower() or "post-commit" in text.lower()
    assert "derived data" in text.lower()
    assert "idempoten" in text.lower()
    assert "FakeEmbeddingProvider" in text
    for needle in ("draft", "archive", "restore", "publish"):
        assert needle in text.lower(), f"architecture freeze missing lifecycle {needle!r}"
    for needle in (
        "ACL-first",
        "allowed article ids",
        "cosine",
        "top-k",
        "top_k",
        "no-answer",
        "FakeEmbeddingProvider",
        "current_version_id",
        "AI_RETRIEVAL_ACCESS",
        "Metadata is never authorization",
        "Fake score is ranking-only",
        "No production relevance threshold",
        "text-embedding-3-small",
        "OpenAIEmbeddingProvider",
        "reindex-published",
        "1536",
        "Recall@K",
        "threshold analysis",
        "multilingual",
        "NO_ANSWER",
        "ONBOARDAI_AI7_LIVE_OPENAI",
        "AI-9C Telegram AI client implemented",
        "POST /api/v1/ai/chat",
        "AI-10A",
        "text-embedding-3-small",
    ):
        assert needle.lower() in text.lower(), f"architecture freeze missing retrieval {needle!r}"


def test_architecture_freeze_rejects_external_vector_saas_as_choice() -> None:
    text = ARCHITECTURE.read_text(encoding="utf-8")
    forbidden = text.split("## Frozen decisions", 1)[0]
    assert "Qdrant" in forbidden
    assert "Weaviate" in forbidden
    assert "Pinecone" in forbidden
    decisions = text.split("## Frozen decisions", 1)[1]
    assert "PostgreSQL + pgvector" in decisions
    assert "Qdrant" not in decisions.split("## Embedding", 1)[0]


def test_ai7_eval_report_document_exists() -> None:
    assert EVAL_REPORT.is_file()
    text = EVAL_REPORT.read_text(encoding="utf-8")
    for needle in (
        "# AI-7 Retrieval Evaluation",
        "## Dataset",
        "## Recall",
        "Recall@1",
        "Recall@3",
        "Recall@5",
        "## Top-K",
        "## Score distribution",
        "## Threshold analysis",
        "## Language results",
        "## Chunking results",
        "## No-answer results",
        "NO_ANSWER_CASES",
        "## Security verification",
        "Live OpenAI: `False`",
        "Provider: `fake`",
    ):
        assert needle in text, f"eval report missing {needle!r}"
    assert re.search(r"Recall@1: 0\.\d+", text)
    assert re.search(r"Recall@5: 0\.\d+", text)


def test_ai8_eval_report_document_exists() -> None:
    assert EVAL_REPORT_AI8.is_file()
    text = EVAL_REPORT_AI8.read_text(encoding="utf-8")
    for needle in (
        "# AI-8 Real Retrieval Evaluation",
        "## Dataset",
        "## Model",
        "## Dimensions",
        "## Evaluation methodology",
        "## Fake results",
        "## OpenAI results",
        "## Recall@K",
        "## Score distributions",
        "## Threshold analysis",
        "## Multilingual analysis",
        "## No-answer analysis",
        "## Chunking observations",
        "## Security results",
        "## Cost / operational observations",
        "## Recommendation for top_k",
        "## Recommendation for min_score",
        "## Known limitations",
        "MEASURED",
        "text-embedding-3-small",
        "1536",
        "FakeEmbeddingProvider: **MEASURED**",
    ):
        assert needle in text, f"AI-8 eval report missing {needle!r}"
    assert "min_score" in text
    assert "top_k" in text
    openai_measured = "OpenAI `text-embedding-3-small`: **MEASURED**" in text
    openai_not_measured = "OpenAI `text-embedding-3-small`: **NOT MEASURED**" in text
    assert openai_measured != openai_not_measured
    if openai_not_measured:
        assert "NOT MEASURED" in text
    else:
        assert re.search(r"Recall@5: 0\.\d+", text)


def test_ai9a_service_invariants() -> None:
    text = ARCHITECTURE.read_text(encoding="utf-8")
    for needle in (
        "AI-9A",
        "AIChatService",
        "ArticleService remains ACL authority",
        "KnowledgeRetriever remains ACL boundary",
        "Explicitly not in AI-9A",
        "conversation persistence is NOT implemented",
        "AI-8 live OpenAI evaluation remains NOT MEASURED",
        "no production min_score",
    ):
        assert needle in text, f"architecture freeze missing AI-9A {needle!r}"

    chat_src = (ROOT / "app" / "services" / "ai" / "chat.py").read_text(encoding="utf-8")
    assert "AIConversation" not in chat_src
    assert "ai_conversations" not in chat_src
    assert "AIACLService" not in chat_src
    assert "min_score=" not in chat_src


def test_ai9b_http_chat_is_stateless() -> None:
    text = ARCHITECTURE.read_text(encoding="utf-8")
    for needle in (
        "POST /api/v1/ai/chat",
        "endpoint is stateless",
        "conversation persistence is NOT implemented",
        "AIChatService is the application boundary",
        "KnowledgeRetriever is the ACL boundary",
        "ArticleService remains the only KB ACL authority",
        "tenant comes from authenticated context",
        "request cannot select tenant",
        "no production min_score",
        "AI-8 live OpenAI evaluation remains NOT MEASURED",
    ):
        assert needle in text, f"architecture freeze missing AI-9B {needle!r}"

    router = (ROOT / "app" / "api" / "v1" / "router.py").read_text(encoding="utf-8")
    assert "ai_router" in router
    assert "ai/search" not in router

    api_src = (ROOT / "app" / "api" / "v1" / "ai.py").read_text(encoding="utf-8")
    assert "AIChatService" in api_src
    assert "list_articles" not in api_src
    assert "search_similar" not in api_src
    assert "httpx" not in api_src
    assert "openai.com" not in api_src
    assert "OpenAILLMProvider" not in api_src
    assert "AIACLService" not in api_src
    assert "VectorACL" not in api_src
    assert "AIVisibilityService" not in api_src
    assert "AIConversation" not in api_src
    assert "min_score=" not in api_src


def test_ai9c_telegram_is_thin_http_client() -> None:
    text = ARCHITECTURE.read_text(encoding="utf-8")
    for needle in (
        "AI-9C Telegram AI client implemented",
        "Telegram is NOT an ACL layer",
        "Telegram does NOT access pgvector directly",
        "Telegram does NOT call OpenAI directly",
        "ArticleService remains the only KB authorization authority",
        "KnowledgeRetriever remains the retrieval ACL boundary",
        "AI HTTP API remains stateless",
        "No conversation persistence",
        "No new vector DB",
        "No new migration",
        "No production min_score change",
        "No top_k change",
        "authenticated backend identity",
        "/api/v1/ai/chat",
    ):
        assert needle in text, f"architecture freeze missing AI-9C {needle!r}"

    handlers = (ROOT / "app" / "bot" / "handlers" / "__init__.py").read_text(
        encoding="utf-8"
    )
    includes = [
        line.strip() for line in handlers.splitlines() if "include_router(" in line
    ]
    assert includes == [
        "root.include_router(start_router)",
        "root.include_router(onboarding_router)",
        "root.include_router(cabinet_router)",
        "root.include_router(ai_router)",
    ]

    ai_handler = (ROOT / "app" / "bot" / "handlers" / "ai.py").read_text(encoding="utf-8")
    ai_client = (ROOT / "app" / "bot" / "services" / "ai_client.py").read_text(
        encoding="utf-8"
    )
    bot_client = (ROOT / "app" / "bot" / "api" / "client.py").read_text(encoding="utf-8")
    combined = ai_handler + ai_client
    for forbidden in (
        "openai.com",
        "OpenAILLMProvider",
        "OpenAIEmbeddingProvider",
        "knowledge_article_chunks",
        "pgvector",
        "AIChatService",
        "KnowledgeRetriever",
        "ArticleService",
        "AIACLService",
        "AIConversation",
        "min_score=",
        "top_k",
    ):
        assert forbidden not in combined, f"Telegram AI layer must not use {forbidden!r}"
    assert "/api/v1/ai/chat" in bot_client
    assert "post_ai_chat" in bot_client
    fn = bot_client.split("async def post_ai_chat", 1)[1].split("async def ", 1)[0]
    assert '"message": message' in fn
    assert "company_id" not in fn
    assert "employee_id" not in fn


def test_ai10a_production_hardening_invariants() -> None:
    text = ARCHITECTURE.read_text(encoding="utf-8")
    for needle in (
        "Production hardening (AI-10A)",
        "Timeout model",
        "Retry model",
        "Error classification",
        "Request correlation",
        "Safe logging",
        "In-process counters only",
        "retries are bounded",
        "Telegram remains a thin HTTP client",
        "AI-11 is NOT started",
        "never retry",
        "X-Request-ID",
        ".ai7_embedding_cache",
    ):
        assert needle in text, f"architecture freeze missing AI-10A {needle!r}"

    api_src = (ROOT / "app" / "api" / "v1" / "ai.py").read_text(encoding="utf-8")
    chat_src = (ROOT / "app" / "services" / "ai" / "chat.py").read_text(encoding="utf-8")
    handler_src = (ROOT / "app" / "bot" / "handlers" / "ai.py").read_text(encoding="utf-8")
    telegram_src = handler_src + (
        ROOT / "app" / "bot" / "services" / "ai_client.py"
    ).read_text(encoding="utf-8")
    for src, label in ((api_src, "HTTP"), (telegram_src, "Telegram")):
        assert "openai.com" not in src, f"{label} must not call OpenAI"
        assert "knowledge_article_chunks" not in src
        assert "AIACLService" not in src
        assert "AIConversation" not in src
        assert "eval_cache" not in src
        assert ".ai7_embedding_cache" not in src
    assert "min_score=" not in chat_src
    assert "top_k: int = DEFAULT_RETRIEVAL_TOP_K" in chat_src
    schema = (ROOT / "app" / "schemas" / "ai.py").read_text(encoding="utf-8")
    assert "extra=\"forbid\"" in schema or "extra='forbid'" in schema
    for forbidden in ("top_k", "min_score", "model", "provider", "company_id"):
        assert f"{forbidden}:" not in schema.split("class AIChatRequest", 1)[1].split(
            "class AIChatCitation", 1
        )[0]


def test_ai11a_conversation_persistence_foundation() -> None:
    text = ARCHITECTURE.read_text(encoding="utf-8")
    for needle in (
        "Conversation persistence foundation (AI-11A)",
        "conversations are employee-owned",
        "company ownership is enforced",
        "messages belong to conversations",
        "conversation storage is not KB authorization",
        "ArticleService remains KB ACL authority",
        "KnowledgeRetriever remains retrieval ACL boundary",
        "conversation history is not yet supplied to LLM",
        "no conversation HTTP API",
        "no Telegram conversation history",
        "no title generation",
        "no streaming",
        "no WebSocket",
        "no worker",
        "no AI-11B",
    ):
        assert needle in text, f"architecture freeze missing AI-11A {needle!r}"

    api_src = (ROOT / "app" / "api" / "v1" / "ai.py").read_text(encoding="utf-8")
    conv_src = (ROOT / "app" / "services" / "ai" / "conversations.py").read_text(
        encoding="utf-8"
    )
    telegram_src = (ROOT / "app" / "bot" / "handlers" / "ai.py").read_text(
        encoding="utf-8"
    ) + (ROOT / "app" / "bot" / "services" / "ai_client.py").read_text(encoding="utf-8")

    assert "/conversations" not in api_src
    assert "ConversationService" not in api_src
    assert "AIConversation" not in telegram_src
    assert "ConversationService" not in telegram_src

    for forbidden in (
        "from app.services.knowledge",
        "from app.services.ai.retriever",
        "from app.services.ai.prompts",
        "from app.services.ai.chat",
        "list_articles",
        "AIACLService",
        "generate_title",
        "gpt-4o",
        "build_user_prompt",
        "EmployeeRole.HR",
        "EmployeeRole.ADMIN",
    ):
        assert forbidden not in conv_src, f"ConversationService must not use {forbidden}"
    assert "actor_company_id" in conv_src
    assert "actor_employee_id" in conv_src
    assert "ARCHIVED" in conv_src


def test_ai11b_conversation_aware_rag() -> None:
    text = ARCHITECTURE.read_text(encoding="utf-8")
    for needle in (
        "Conversation-aware RAG (AI-11B)",
        "conversation-aware RAG",
        "ConversationService owns conversation persistence",
        "ArticleService remains KB ACL authority",
        "KnowledgeRetriever remains retrieval ACL boundary",
        "conversation history is not KB authority",
        "history is not used for ACL",
        "history is not a citation source",
        "every new question performs retrieval",
        "conversation history is bounded",
        "Telegram remains stateless until AI-11C",
        "no streaming",
        "no WebSockets",
        "no workers",
        "no new vector DB",
        "no min_score calibration",
        "no query rewriting",
        "no AI-11C",
    ):
        assert needle in text, f"architecture freeze missing AI-11B {needle!r}"

    api_src = (ROOT / "app" / "api" / "v1" / "ai.py").read_text(encoding="utf-8")
    chat_src = (ROOT / "app" / "services" / "ai" / "chat.py").read_text(encoding="utf-8")
    prompts_src = (ROOT / "app" / "services" / "ai" / "prompts.py").read_text(
        encoding="utf-8"
    )
    history_src = (ROOT / "app" / "services" / "ai" / "history.py").read_text(
        encoding="utf-8"
    )
    conv_src = (ROOT / "app" / "services" / "ai" / "conversations.py").read_text(
        encoding="utf-8"
    )
    telegram_src = (ROOT / "app" / "bot" / "handlers" / "ai.py").read_text(
        encoding="utf-8"
    ) + (ROOT / "app" / "bot" / "services" / "ai_client.py").read_text(encoding="utf-8")
    schema = (ROOT / "app" / "schemas" / "ai.py").read_text(encoding="utf-8")
    bot_client = (ROOT / "app" / "bot" / "api" / "client.py").read_text(encoding="utf-8")

    assert "ConversationService" in chat_src
    assert "complete_turn" in chat_src
    assert "MAX_CHAT_HISTORY_MESSAGES" in chat_src
    assert "select_history_for_llm" in chat_src
    assert "session.execute" not in chat_src
    assert "knowledge_article_chunks" not in chat_src
    assert "openai.com" not in chat_src
    assert "min_score=" not in chat_src
    assert "top_k: int = DEFAULT_RETRIEVAL_TOP_K" in chat_src
    assert "AIACLService" not in chat_src
    assert "list_articles" not in chat_src

    assert "<conversation_history>" in prompts_src
    assert "<current_question>" in prompts_src
    assert "<knowledge_context>" in prompts_src
    assert "not knowledge-base sources" in prompts_src
    assert "Never assign source ids to conversation history" in prompts_src

    assert "MAX_CHAT_HISTORY_MESSAGES" in history_src
    assert "MAX_CHAT_HISTORY_CHARS" in history_src

    assert "from app.services.ai.retriever" not in conv_src
    assert "from app.services.ai.llm" not in conv_src
    assert "complete_turn" in conv_src

    assert "ConversationService" not in api_src
    assert "openai.com" not in api_src
    assert "knowledge_article_chunks" not in api_src
    request_block = schema.split("class AIChatRequest", 1)[1].split(
        "class AIChatCitation", 1
    )[0]
    assert "conversation_id" in request_block
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
    ):
        assert f"    {forbidden}:" not in request_block
    response_block = schema.split("class AIChatResponse", 1)[1]
    assert "conversation_id" in response_block

    assert "ConversationService" not in telegram_src
    fn = bot_client.split("async def post_ai_chat", 1)[1].split("async def ", 1)[0]
    assert "conversation_id" in fn
    assert '"message": message' in fn
    assert "company_id" not in fn
    assert "alembic/versions" not in chat_src


def test_ai11c_telegram_conversation_pointer() -> None:
    text = ARCHITECTURE.read_text(encoding="utf-8")
    for needle in (
        "Telegram conversation persistence (AI-11C)",
        "Telegram maintains an **ephemeral current conversation pointer** in Redis",
        "PostgreSQL remains the source of truth for conversations and messages",
        "Redis is only the Telegram session pointer",
        "Telegram never authorizes conversations",
        "HTTP API remains the authorization boundary",
        "ArticleService remains KB ACL authority",
        "KnowledgeRetriever remains retrieval ACL boundary",
        "Telegram never calls OpenAI",
        "Telegram never accesses vectors",
        "no conversation schema changes",
        "no new migration",
        "no streaming",
        "no workers",
        "no frontend",
        "no CRUD conversation API",
        "no AI-12",
    ):
        assert needle in text, f"architecture freeze missing AI-11C {needle!r}"

    store_src = (ROOT / "app" / "bot" / "services" / "ai_conversation.py").read_text(
        encoding="utf-8"
    )
    handler_src = (ROOT / "app" / "bot" / "handlers" / "ai.py").read_text(
        encoding="utf-8"
    )
    client_src = (ROOT / "app" / "bot" / "services" / "ai_client.py").read_text(
        encoding="utf-8"
    )
    bot_client = (ROOT / "app" / "bot" / "api" / "client.py").read_text(encoding="utf-8")
    combined = handler_src + client_src + store_src

    assert "bot:ai:conversation:" in store_src
    assert "CURRENT_CONVERSATIONS" not in combined
    assert "@lru_cache" not in store_src
    assert "ConversationService" not in combined
    assert "AIChatService" not in combined
    assert "openai.com" not in combined
    assert "knowledge_article_chunks" not in combined
    assert "session.execute" not in combined
    assert "sqlalchemy" not in combined.lower()
    assert "AIACLService" not in combined
    fn = bot_client.split("async def post_ai_chat", 1)[1].split("async def ", 1)[0]
    assert "conversation_id" in fn
    for forbidden in (
        "company_id",
        "employee_id",
        "actor_role",
        "tenant_id",
        "top_k",
        "min_score",
        "provider",
    ):
        assert forbidden not in fn
    assert "Command(\"newchat\")" in handler_src or "Command('newchat')" in handler_src
    assert "alembic/versions" not in combined


def test_ai12a_employee_frontend_chat() -> None:
    text = ARCHITECTURE.read_text(encoding="utf-8")
    for needle in (
        "Employee frontend AI chat (AI-12A)",
        "Frontend is never an authorization boundary",
        "ArticleService remains the only KB ACL authority",
        "KnowledgeRetriever remains the retrieval ACL boundary",
        "AIChatService remains the orchestration layer",
        "ConversationService remains conversation ownership authority",
        "Telegram remains unchanged",
        "AI-8 live OpenAI evaluation remains NOT MEASURED",
        "no conversation HTTP CRUD API",
        "no streaming",
        "no WebSockets",
        "no SSE",
        "no workers",
        "no Prometheus",
        "no ANN",
        "no min_score",
        "no retrieval redesign",
        "no AI-12B",
    ):
        assert needle in text, f"architecture freeze missing AI-12A {needle!r}"

    routes = (ROOT / "frontend" / "src" / "routes" / "AppRoutes.tsx").read_text(
        encoding="utf-8"
    )
    nav = (ROOT / "frontend" / "src" / "lib" / "navigation.ts").read_text(
        encoding="utf-8"
    )
    api = (ROOT / "frontend" / "src" / "services" / "aiApi.ts").read_text(
        encoding="utf-8"
    )
    chat = (ROOT / "frontend" / "src" / "components" / "ai" / "AIChat.tsx").read_text(
        encoding="utf-8"
    )
    schema = (ROOT / "app" / "schemas" / "ai.py").read_text(encoding="utf-8")
    telegram = (ROOT / "app" / "bot" / "handlers" / "ai.py").read_text(
        encoding="utf-8"
    )

    # Phase 9K: employee web AI is not a primary channel. The route stays as a
    # safe redirect; Telegram remains the employee AI/learning surface.
    assert 'path="ai"' in routes
    assert 'Navigate to="/employee" replace' in routes
    assert "EmployeeAIPage" not in routes
    assert "workspacePath('employee', '/ai')" not in nav
    assert "nav.aiAssistant" not in nav
    assert "postAIChat" in api
    assert "/api/v1/ai/chat" in api
    assert "conversation_id" in api
    assert "company_id" not in api
    assert "employee_id" not in api
    assert "tenant_id" not in api
    assert "openai.com" not in api
    assert "retry: false" in chat
    assert "startNewChat" in chat
    assert "EventSource" not in chat
    assert "WebSocket" not in chat
    assert "conversation_id" in schema
    assert "Command(\"newchat\")" in telegram or "Command('newchat')" in telegram


def test_ai12b_conversation_history() -> None:
    text = ARCHITECTURE.read_text(encoding="utf-8")
    for needle in (
        "Employee conversation history (AI-12B)",
        "GET /api/v1/ai/conversations",
        "Archive is the delete convention",
        "Frontend is never an authorization boundary",
        "ArticleService remains the only KB ACL authority",
        "KnowledgeRetriever remains the retrieval ACL boundary",
        "ConversationService remains conversation ownership authority",
        "Telegram remains unchanged",
        "AI-8 live OpenAI evaluation remains NOT MEASURED",
        "no streaming",
        "no WebSockets",
        "no SSE",
        "no workers",
        "no LLM-generated titles",
        "no AI-13",
    ):
        assert needle in text, f"architecture freeze missing AI-12B {needle!r}"

    api_src = (ROOT / "app" / "api" / "v1" / "ai_conversations.py").read_text(
        encoding="utf-8"
    )
    chat_api = (ROOT / "app" / "api" / "v1" / "ai.py").read_text(encoding="utf-8")
    schema = (ROOT / "app" / "schemas" / "ai.py").read_text(encoding="utf-8")
    frontend_api = (ROOT / "frontend" / "src" / "services" / "aiApi.ts").read_text(
        encoding="utf-8"
    )
    chat = (ROOT / "frontend" / "src" / "components" / "ai" / "AIChat.tsx").read_text(
        encoding="utf-8"
    )
    telegram = (ROOT / "app" / "bot" / "handlers" / "ai.py").read_text(encoding="utf-8")
    model = (ROOT / "app" / "db" / "models" / "ai_message.py").read_text(
        encoding="utf-8"
    )

    assert "list_ai_conversations" in api_src
    assert "get_ai_conversation" in api_src
    assert "delete_ai_conversation" in api_src
    assert "include_archived=False" in api_src
    assert "ConversationService" not in chat_api
    assert "list_ai_conversations" not in chat_api
    assert "AIConversationListResponse" in schema
    assert "company_id" not in schema.split("class AIConversationSummary", 1)[1].split(
        "class AIConversationListResponse", 1
    )[0]
    assert "employee_id" not in schema.split("class AIConversationSummary", 1)[1]
    assert "listAIConversations" in frontend_api
    assert "company_id" not in frontend_api
    assert "AIConversationHistory" in chat
    assert "EventSource" not in chat
    assert "WebSocket" not in chat
    assert "citations" in model
    assert "Command(\"newchat\")" in telegram or "Command('newchat')" in telegram
    router = (ROOT / "app" / "api" / "v1" / "router.py").read_text(encoding="utf-8")
    assert "ai_conversations_router" in router


def test_ai8_rag_end_to_end_evaluation() -> None:
    text = ARCHITECTURE.read_text(encoding="utf-8")
    for needle in (
        "End-to-end RAG evaluation (AI-8)",
        "python -m scripts.evaluate_rag",
        "Small evaluation sample",
        "does not change retrieval",
        "tests/ai/evaluation/dataset.json",
        "AI-8 live OpenAI evaluation remains NOT MEASURED",
        "no production min_score",
    ):
        assert needle in text, f"architecture freeze missing AI-8 RAG {needle!r}"

    report = ROOT / "docs" / "ai" / "ai8-rag-evaluation.md"
    assert report.is_file()
    report_text = report.read_text(encoding="utf-8")
    for needle in (
        "# AI-8 Evaluation Report",
        "## Dataset",
        "## Retrieval",
        "## Answer",
        "## Groundedness",
        "## Citation accuracy",
        "## No-answer",
        "## Latency",
        "## Security",
        "Small evaluation sample",
        "Fake embeddings + FakeLLM: **MEASURED**",
    ):
        assert needle in report_text, f"AI-8 RAG report missing {needle!r}"
    live_measured = "Live OpenAI embeddings+LLM: **MEASURED**" in report_text
    live_not = "Live OpenAI embeddings+LLM: **NOT MEASURED**" in report_text
    assert live_measured != live_not
    chat_src = (ROOT / "app" / "services" / "ai" / "chat.py").read_text(
        encoding="utf-8"
    )
    assert "min_score=" not in chat_src
    constants = (ROOT / "app" / "core" / "ai_constants.py").read_text(encoding="utf-8")
    assert "DEFAULT_RETRIEVAL_TOP_K = 5" in constants


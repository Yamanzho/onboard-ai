"""LLM and embedding providers stay independently configurable."""

from __future__ import annotations

from pathlib import Path

from app.core.ai_constants import (
    KB_CHUNK_VECTOR_DIMENSION,
    OPENAI_EMBEDDING_DIMENSION,
)
from app.core.config import Settings
from app.db.enums import KnowledgeIndexStatus
from app.services.ai.embedding_identity import (
    EmbeddingIdentity,
    embedding_compatibility,
    embedding_identity_from_provider,
)
from app.services.ai.embeddings import get_embedding_provider
from app.services.ai.llm import get_llm_provider
from app.services.ai.openai_compatible_llm import OpenAICompatibleLLMProvider
from app.services.ai.openai_embeddings import OpenAIEmbeddingProvider


def test_qwen_chat_does_not_change_embedding_identity() -> None:
    settings = Settings(
        _env_file=None,
        ai_llm_provider="openai_compatible",
        ai_llm_model="qwen-test",
        ai_llm_api_key="secret-qwen-123",
        ai_llm_base_url="https://example.test/compatible-mode/v1",
        ai_embedding_provider="openai",
        ai_embedding_model="text-embedding-3-small",
        ai_embedding_dimension=1536,
        ai_embedding_api_key="secret-openai-123",
    )
    llm = get_llm_provider(settings)
    embeddings = get_embedding_provider(settings)
    assert isinstance(llm, OpenAICompatibleLLMProvider)
    assert llm.model == "qwen-test"
    assert isinstance(embeddings, OpenAIEmbeddingProvider)
    identity = embedding_identity_from_provider(embeddings)
    assert identity == EmbeddingIdentity(
        provider="openai",
        model="text-embedding-3-small",
        dimension=1536,
    )
    assert identity.dimension == OPENAI_EMBEDDING_DIMENSION
    assert identity.dimension == KB_CHUNK_VECTOR_DIMENSION
    compat = embedding_compatibility(
        active=identity,
        index_status=KnowledgeIndexStatus.INDEXED.value,
        embedding_provider="openai",
        embedding_model="text-embedding-3-small",
        embedding_dimension=1536,
    )
    assert compat.compatible is True
    assert compat.reindex_required is False


def test_retriever_has_no_llm_provider_branches() -> None:
    root = Path(__file__).resolve().parents[2]
    retriever = (root / "app" / "services" / "ai" / "retriever.py").read_text(
        encoding="utf-8"
    )
    for needle in (
        "get_llm_provider",
        "AnthropicLLMProvider",
        "GeminiLLMProvider",
        "OpenAICompatibleLLMProvider",
        "ai_llm_provider",
    ):
        assert needle not in retriever


def test_pgvector_dimension_constant_unchanged() -> None:
    chunk_model = (
        Path(__file__).resolve().parents[2]
        / "app"
        / "db"
        / "models"
        / "knowledge_article_chunk.py"
    )
    text = chunk_model.read_text(encoding="utf-8")
    assert KB_CHUNK_VECTOR_DIMENSION == 1536
    assert "Vector(KB_CHUNK_VECTOR_DIMENSION)" in text

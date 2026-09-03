"""Phase 7F: embedding-space compatibility enforcement."""

from __future__ import annotations

from collections.abc import Sequence
from uuid import UUID

import pytest

from app.core.ai_constants import KB_CHUNK_VECTOR_DIMENSION, LEXICAL_FLOOR_SCORE
from app.db.models.company import Company
from app.db.models.employee import Employee
from app.db.uow import UnitOfWork
from app.repositories.knowledge_article_chunk import KnowledgeArticleChunkRepository
from app.schemas.knowledge.version import article_version_response
from app.services.ai.embedding_identity import (
    EmbeddingCompatibilityState,
    embedding_compatibility,
    embedding_identity_from_provider,
    version_embedding_compatibility,
)
from app.services.ai.embeddings import FakeEmbeddingProvider
from app.services.ai.indexer import KnowledgeChunkIndexer
from app.services.ai.retriever import KnowledgeRetriever
from app.services.knowledge.article_service import ArticleService
from tests.conftest import _uow_factory


class _NamedEmbeddings:
    dimension = KB_CHUNK_VECTOR_DIMENSION

    def __init__(self, *, provider_name: str, model: str) -> None:
        self.provider_name = provider_name
        self.model = model
        self._delegate = FakeEmbeddingProvider()

    async def embed(self, text: str) -> list[float]:
        return (await self.embed_batch((text,)))[0]

    async def embed_batch(self, texts: Sequence[str]) -> list[list[float]]:
        return await self._delegate.embed_batch(texts)


class _WrongRuntimeDimension:
    provider_name = "fake"
    model = "fake"
    dimension = KB_CHUNK_VECTOR_DIMENSION

    async def embed(self, text: str) -> list[float]:
        return [0.0, 1.0, 0.0]

    async def embed_batch(self, texts: Sequence[str]) -> list[list[float]]:
        return [[0.0, 1.0, 0.0] for _ in texts]


async def _publish(
    service: ArticleService,
    company_id: UUID,
    *,
    title: str,
    body: str,
):
    article = await service.create_article(
        company_id=company_id,
        actor_company_id=company_id,
        title=title,
        body=body,
    )
    return await service.publish_article(article.id, company_id=company_id)


async def _reindex(article, company_id: UUID, provider) -> None:
    await KnowledgeChunkIndexer(
        uow_factory=_uow_factory,
        embedding_provider=provider,
    ).index_published_version(
        actor_company_id=company_id,
        article_id=article.id,
        version_id=article.current_version_id,
    )


async def _load_version(company_id: UUID, version_id: UUID):
    async with UnitOfWork() as uow:
        await uow.enter_tenant(company_id)
        version = await uow.knowledge_article_versions.get_by_id(version_id)
        assert version is not None
        return version


def test_exact_embedding_identity_is_required() -> None:
    active = embedding_identity_from_provider(
        _NamedEmbeddings(provider_name=" OpenAI ", model="model-A")
    )
    compatible = embedding_compatibility(
        active=active,
        index_status="indexed",
        embedding_provider="openai",
        embedding_model="model-A",
        embedding_dimension=KB_CHUNK_VECTOR_DIMENSION,
    )
    assert compatible.state is EmbeddingCompatibilityState.COMPATIBLE

    provider_mismatch = embedding_compatibility(
        active=active,
        index_status="indexed",
        embedding_provider="fake",
        embedding_model="model-A",
        embedding_dimension=KB_CHUNK_VECTOR_DIMENSION,
    )
    model_mismatch = embedding_compatibility(
        active=active,
        index_status="indexed",
        embedding_provider="openai",
        embedding_model="model-B",
        embedding_dimension=KB_CHUNK_VECTOR_DIMENSION,
    )
    dimension_mismatch = embedding_compatibility(
        active=active,
        index_status="indexed",
        embedding_provider="openai",
        embedding_model="model-A",
        embedding_dimension=3072,
    )
    missing = embedding_compatibility(
        active=active,
        index_status="indexed",
        embedding_provider=None,
        embedding_model=None,
        embedding_dimension=None,
    )
    assert provider_mismatch.state is EmbeddingCompatibilityState.INCOMPATIBLE_PROVIDER
    assert model_mismatch.state is EmbeddingCompatibilityState.INCOMPATIBLE_MODEL
    assert dimension_mismatch.state is EmbeddingCompatibilityState.INCOMPATIBLE_DIMENSION
    assert missing.state is EmbeddingCompatibilityState.MISSING_INDEX_METADATA
    assert all(
        result.reindex_required
        for result in (provider_mismatch, model_mismatch, dimension_mismatch, missing)
    )


async def test_mixed_corpus_filters_vector_ids_but_preserves_lexical_hits(
    article_service: ArticleService,
    company_a: Company,
    employee_a: Employee,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    article_a = await _publish(
        article_service,
        company_a.id,
        title="Model A",
        body="alphacompatibilityterm",
    )
    article_b = await _publish(
        article_service,
        company_a.id,
        title="Model B",
        body="betacompatibilityterm",
    )
    await _reindex(
        article_a,
        company_a.id,
        _NamedEmbeddings(provider_name="openai", model="model-A"),
    )
    active = _NamedEmbeddings(provider_name="openai", model="model-B")
    await _reindex(article_b, company_a.id, active)

    searched_ids: list[set[UUID]] = []
    original = KnowledgeArticleChunkRepository.search_similar_current_published

    async def capture_search(self, **kwargs):
        searched_ids.append(set(kwargs["allowed_article_ids"]))
        return await original(self, **kwargs)

    monkeypatch.setattr(
        KnowledgeArticleChunkRepository,
        "search_similar_current_published",
        capture_search,
    )
    retriever = KnowledgeRetriever(
        uow_factory=_uow_factory,
        article_service=article_service,
        embedding_provider=active,
    )
    hits = await retriever.retrieve(
        "alphacompatibilityterm",
        actor_company_id=company_a.id,
        actor_employee_id=employee_a.id,
        actor_role=employee_a.role,
    )

    assert searched_ids
    assert all(ids == {article_b.id} for ids in searched_ids)
    lexical_a = [hit for hit in hits if hit.article_id == article_a.id]
    assert lexical_a
    assert all(hit.score == LEXICAL_FLOOR_SCORE for hit in lexical_a)


@pytest.mark.parametrize(
    ("active_provider", "active_model"),
    [
        ("openai", "model-B"),
        ("fake", "model-A"),
    ],
)
async def test_only_incompatible_vectors_skip_vector_sql_and_use_lexical(
    article_service: ArticleService,
    company_a: Company,
    employee_a: Employee,
    monkeypatch: pytest.MonkeyPatch,
    active_provider: str,
    active_model: str,
) -> None:
    article = await _publish(
        article_service,
        company_a.id,
        title="Old model",
        body="onlyincompatibleterm",
    )
    await _reindex(
        article,
        company_a.id,
        _NamedEmbeddings(provider_name="openai", model="model-A"),
    )

    async def fail_vector_search(self, **kwargs):
        raise AssertionError("incompatible corpus must not issue vector SQL")

    monkeypatch.setattr(
        KnowledgeArticleChunkRepository,
        "search_similar_current_published",
        fail_vector_search,
    )
    hits = await KnowledgeRetriever(
        uow_factory=_uow_factory,
        article_service=article_service,
        embedding_provider=_NamedEmbeddings(
            provider_name=active_provider,
            model=active_model,
        ),
    ).retrieve(
        "onlyincompatibleterm",
        actor_company_id=company_a.id,
        actor_employee_id=employee_a.id,
        actor_role=employee_a.role,
    )
    assert hits
    assert all(hit.score == LEXICAL_FLOOR_SCORE for hit in hits)


async def test_runtime_dimension_mismatch_skips_vector_sql(
    article_service: ArticleService,
    company_a: Company,
    employee_a: Employee,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    await _publish(
        article_service,
        company_a.id,
        title="Runtime width",
        body="runtimewidthterm",
    )

    async def fail_vector_search(self, **kwargs):
        raise AssertionError("malformed vector must not reach pgvector")

    monkeypatch.setattr(
        KnowledgeArticleChunkRepository,
        "search_similar_current_published",
        fail_vector_search,
    )
    hits = await KnowledgeRetriever(
        uow_factory=_uow_factory,
        article_service=article_service,
        embedding_provider=_WrongRuntimeDimension(),
    ).retrieve(
        "runtimewidthterm",
        actor_company_id=company_a.id,
        actor_employee_id=employee_a.id,
        actor_role=employee_a.role,
    )
    assert hits
    assert all(hit.score == LEXICAL_FLOOR_SCORE for hit in hits)


async def test_reindex_with_active_model_repairs_compatibility_and_vector_search(
    article_service: ArticleService,
    company_a: Company,
    employee_a: Employee,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    article = await _publish(
        article_service,
        company_a.id,
        title="Repair",
        body="reindexrepairterm",
    )
    model_a = _NamedEmbeddings(provider_name="openai", model="model-A")
    model_b = _NamedEmbeddings(provider_name="openai", model="model-B")
    await _reindex(article, company_a.id, model_a)
    assert article.current_version_id is not None

    before = await _load_version(company_a.id, article.current_version_id)
    active_identity = embedding_identity_from_provider(model_b)
    before_state = version_embedding_compatibility(before, active=active_identity)
    before_api = article_version_response(before, active=active_identity)
    assert before_state.state is EmbeddingCompatibilityState.INCOMPATIBLE_MODEL
    assert before_api.embedding_compatible is False
    assert before_api.reindex_required is True
    assert before_api.embedding_incompatibility_reason == "model_changed"

    await _reindex(article, company_a.id, model_b)
    after = await _load_version(company_a.id, article.current_version_id)
    after_api = article_version_response(after, active=active_identity)
    assert after_api.embedding_compatible is True
    assert after_api.reindex_required is False
    assert after_api.embedding_incompatibility_reason is None

    vector_calls = 0
    original = KnowledgeArticleChunkRepository.search_similar_current_published

    async def count_search(self, **kwargs):
        nonlocal vector_calls
        vector_calls += 1
        return await original(self, **kwargs)

    monkeypatch.setattr(
        KnowledgeArticleChunkRepository,
        "search_similar_current_published",
        count_search,
    )
    hits = await KnowledgeRetriever(
        uow_factory=_uow_factory,
        article_service=article_service,
        embedding_provider=model_b,
    ).retrieve(
        "reindexrepairterm",
        actor_company_id=company_a.id,
        actor_employee_id=employee_a.id,
        actor_role=employee_a.role,
    )
    assert vector_calls > 0
    assert any(hit.article_id == article.id for hit in hits)

"""AI-4 KnowledgeRetriever: validation, ranking, current-version, dedupe."""

from __future__ import annotations

from collections.abc import Sequence
from uuid import uuid4

import pytest

from app.core.ai_constants import (
    DEFAULT_RETRIEVAL_TOP_K,
    KB_CHUNK_VECTOR_DIMENSION,
    MAX_CHUNKS_PER_ARTICLE_RESULT,
    MAX_RETRIEVAL_QUERY_CHARS,
    MAX_RETRIEVAL_TOP_K,
)
from app.core.exceptions import ForbiddenError, NotFoundError, ValidationError
from app.db.enums import EmployeeRole, PlatformRole
from app.db.models.company import Company
from app.db.models.employee import Employee
from app.db.uow import UnitOfWork
from app.services.ai.embeddings import FakeEmbeddingProvider
from app.services.ai.retriever import KnowledgeRetriever
from app.services.knowledge.article_service import ArticleService
from tests.conftest import _uow_factory


class _BoomEmbeddings:
    dimension = KB_CHUNK_VECTOR_DIMENSION

    async def embed(self, text: str) -> list[float]:
        raise RuntimeError("embedding backend down")

    async def embed_batch(self, texts: Sequence[str]) -> list[list[float]]:
        raise RuntimeError("embedding backend down")


@pytest.fixture
def retriever(article_service: ArticleService) -> KnowledgeRetriever:
    return KnowledgeRetriever(
        uow_factory=_uow_factory,
        article_service=article_service,
        embedding_provider=FakeEmbeddingProvider(),
    )


async def _publish(
    article_service: ArticleService,
    company: Company,
    *,
    title: str,
    body: str,
):
    article = await article_service.create_article(
        company_id=company.id,
        actor_company_id=company.id,
        title=title,
        body=body,
    )
    return await article_service.publish_article(article.id, company_id=company.id)


async def test_empty_and_whitespace_query_rejected(
    retriever: KnowledgeRetriever,
    company_a: Company,
    employee_a: Employee,
) -> None:
    kwargs = dict(
        actor_company_id=company_a.id,
        actor_employee_id=employee_a.id,
        actor_role=EmployeeRole.EMPLOYEE.value,
    )
    with pytest.raises(ValidationError, match="empty"):
        await retriever.retrieve("", **kwargs)
    with pytest.raises(ValidationError, match="empty"):
        await retriever.retrieve("   \n\t  ", **kwargs)
    with pytest.raises(ValidationError, match="empty"):
        await retriever.retrieve("\u00a0\u2003", **kwargs)
    with pytest.raises(ValidationError, match="string"):
        await retriever.retrieve(None, **kwargs)  # type: ignore[arg-type]


async def test_extremely_long_query_rejected(
    retriever: KnowledgeRetriever,
    company_a: Company,
    employee_a: Employee,
) -> None:
    kwargs = dict(
        actor_company_id=company_a.id,
        actor_employee_id=employee_a.id,
        actor_role=EmployeeRole.EMPLOYEE.value,
    )
    with pytest.raises(ValidationError, match="at most"):
        await retriever.retrieve("x" * (MAX_RETRIEVAL_QUERY_CHARS + 1), **kwargs)
    with pytest.raises(ValidationError, match="at most"):
        await retriever.retrieve("я" * (MAX_RETRIEVAL_QUERY_CHARS + 1), **kwargs)
    accepted = await retriever.retrieve("қ" * MAX_RETRIEVAL_QUERY_CHARS, **kwargs)
    assert accepted == [] or isinstance(accepted, list)


async def test_top_k_validation(
    retriever: KnowledgeRetriever,
    company_a: Company,
    employee_a: Employee,
) -> None:
    kwargs = dict(
        query="vpn",
        actor_company_id=company_a.id,
        actor_employee_id=employee_a.id,
        actor_role=EmployeeRole.EMPLOYEE.value,
    )
    with pytest.raises(ValidationError, match="top_k"):
        await retriever.retrieve(**kwargs, top_k=0)
    with pytest.raises(ValidationError, match="top_k"):
        await retriever.retrieve(**kwargs, top_k=MAX_RETRIEVAL_TOP_K + 1)
    with pytest.raises(ValidationError, match="top_k"):
        await retriever.retrieve(**kwargs, top_k=True)  # type: ignore[arg-type]
    with pytest.raises(ValidationError, match="top_k"):
        await retriever.retrieve(**kwargs, top_k=5.0)  # type: ignore[arg-type]
    with pytest.raises(ValidationError, match="top_k"):
        await retriever.retrieve(**kwargs, top_k="5")  # type: ignore[arg-type]


async def test_unicode_ru_kk_en_queries_are_accepted(
    article_service: ArticleService,
    retriever: KnowledgeRetriever,
    company_a: Company,
    employee_a: Employee,
) -> None:
    await _publish(
        article_service,
        company_a,
        title="Отпуск / Демалыс / Vacation",
        body="Подайте заявление за три дня. Өтінішті үш күн бұрын беріңіз.",
    )
    for query in ("Отпуск", "Демалыс", "Vacation"):
        hits = await retriever.retrieve(
            query,
            actor_company_id=company_a.id,
            actor_employee_id=employee_a.id,
            actor_role=EmployeeRole.EMPLOYEE.value,
        )
        assert isinstance(hits, list)


async def test_exact_chunk_text_ranks_first(
    article_service: ArticleService,
    retriever: KnowledgeRetriever,
    company_a: Company,
    employee_a: Employee,
) -> None:
    unique_a = f"ALPHA_RANK_{uuid4().hex}"
    unique_b = f"BETA_RANK_{uuid4().hex}"
    article_a = await _publish(
        article_service, company_a, title="Alpha policy", body=unique_a
    )
    await _publish(article_service, company_a, title="Beta policy", body=unique_b)
    async with UnitOfWork() as uow:
        await uow.enter_tenant(company_a.id)
        stored = await uow.knowledge_article_chunks.list_by_version_id(
            article_a.current_version_id  # type: ignore[arg-type]
        )
    assert stored
    exact = stored[0].content

    hits = await retriever.retrieve(
        exact,
        actor_company_id=company_a.id,
        actor_employee_id=employee_a.id,
        actor_role=EmployeeRole.EMPLOYEE.value,
        top_k=5,
    )
    assert hits
    assert hits[0].article_id == article_a.id
    assert hits[0].article_title == "Alpha policy"
    assert unique_a in hits[0].content
    assert hits[0].score == pytest.approx(1.0)
    assert 0.0 <= hits[-1].score <= 1.0
    assert hits == sorted(hits, key=lambda h: (-h.score, h.article_id, h.chunk_index))


async def test_retrieve_is_deterministic(
    article_service: ArticleService,
    retriever: KnowledgeRetriever,
    company_a: Company,
    employee_a: Employee,
) -> None:
    await _publish(
        article_service,
        company_a,
        title="Stable retrieve",
        body="Same published handbook text.",
    )
    kwargs = dict(
        query="Stable retrieve",
        actor_company_id=company_a.id,
        actor_employee_id=employee_a.id,
        actor_role=EmployeeRole.EMPLOYEE.value,
        top_k=DEFAULT_RETRIEVAL_TOP_K,
    )
    first = await retriever.retrieve(**kwargs)
    second = await retriever.retrieve(**kwargs)
    assert [(h.chunk_id, h.score) for h in first] == [
        (h.chunk_id, h.score) for h in second
    ]


async def test_current_version_only_not_historical(
    article_service: ArticleService,
    retriever: KnowledgeRetriever,
    company_a: Company,
    employee_a: Employee,
) -> None:
    v1_token = f"HIST_V1_{uuid4().hex}"
    v2_token = f"CUR_V2_{uuid4().hex}"
    article = await _publish(
        article_service, company_a, title="Versioned", body=v1_token
    )
    updated = await article_service.update_article(
        article.id,
        company_id=company_a.id,
        title="Versioned",
        body=v2_token,
    )
    assert updated.current_version_id != article.current_version_id

    old = await retriever.retrieve(
        v1_token,
        actor_company_id=company_a.id,
        actor_employee_id=employee_a.id,
        actor_role=EmployeeRole.EMPLOYEE.value,
    )
    assert all(v1_token not in hit.content for hit in old)

    current = await retriever.retrieve(
        v2_token,
        actor_company_id=company_a.id,
        actor_employee_id=employee_a.id,
        actor_role=EmployeeRole.EMPLOYEE.value,
    )
    assert current
    assert current[0].version_id == updated.current_version_id
    assert v2_token in current[0].content


async def test_unpublished_and_archived_are_not_retrieved(
    article_service: ArticleService,
    retriever: KnowledgeRetriever,
    company_a: Company,
    employee_a: Employee,
) -> None:
    draft_token = f"DRAFT_{uuid4().hex}"
    await article_service.create_article(
        company_id=company_a.id,
        actor_company_id=company_a.id,
        title="Draft only",
        body=draft_token,
    )
    archived_token = f"ARCH_{uuid4().hex}"
    published = await _publish(
        article_service, company_a, title="Soon gone", body=archived_token
    )
    await article_service.archive_article(published.id, company_id=company_a.id)

    draft_hits = await retriever.retrieve(
        draft_token,
        actor_company_id=company_a.id,
        actor_employee_id=employee_a.id,
        actor_role=EmployeeRole.EMPLOYEE.value,
    )
    arch_hits = await retriever.retrieve(
        archived_token,
        actor_company_id=company_a.id,
        actor_employee_id=employee_a.id,
        actor_role=EmployeeRole.EMPLOYEE.value,
    )
    assert all(draft_token not in h.content for h in draft_hits)
    assert all(archived_token not in h.content for h in arch_hits)


async def test_per_article_chunk_cap(
    article_service: ArticleService,
    retriever: KnowledgeRetriever,
    company_a: Company,
    employee_a: Employee,
) -> None:
    paragraph = "Onboarding uniform rules. " * 60
    body = "\n\n".join(f"## Part {index}\n{paragraph}" for index in range(5))
    article = await _publish(
        article_service, company_a, title="Long handbook", body=body
    )
    async with UnitOfWork() as uow:
        await uow.enter_tenant(company_a.id)
        stored = await uow.knowledge_article_chunks.list_by_version_id(
            article.current_version_id  # type: ignore[arg-type]
        )
    assert len(stored) > MAX_CHUNKS_PER_ARTICLE_RESULT

    hits = await retriever.retrieve(
        "Onboarding uniform rules",
        actor_company_id=company_a.id,
        actor_employee_id=employee_a.id,
        actor_role=EmployeeRole.EMPLOYEE.value,
        top_k=MAX_RETRIEVAL_TOP_K,
    )
    from_article = [h for h in hits if h.article_id == article.id]
    assert from_article
    assert len(from_article) <= MAX_CHUNKS_PER_ARTICLE_RESULT


async def test_query_is_not_written_to_logs(
    article_service: ArticleService,
    retriever: KnowledgeRetriever,
    company_a: Company,
    employee_a: Employee,
    caplog: pytest.LogCaptureFixture,
) -> None:
    secret = f"EMPLOYEE_SECRET_QUERY_{uuid4().hex}"
    body = f"HANDBOOK_BODY_{uuid4().hex}"
    await _publish(article_service, company_a, title="Quiet", body=body)
    with caplog.at_level("INFO", logger="app.kb.retrieve"):
        await retriever.retrieve(
            secret,
            actor_company_id=company_a.id,
            actor_employee_id=employee_a.id,
            actor_role=EmployeeRole.EMPLOYEE.value,
        )
    combined = " ".join(record.getMessage() for record in caplog.records)
    assert secret not in combined
    assert body not in combined
    assert "embedding=[" not in combined
    assert f"actor_role={EmployeeRole.EMPLOYEE.value}" in combined
    assert f"company_id={company_a.id}" in combined
    assert "hit_count=" in combined
    assert "duration_ms=" in combined
    assert "result=" in combined


async def test_no_default_production_relevance_threshold() -> None:
    import inspect

    default = inspect.signature(KnowledgeRetriever.retrieve).parameters["min_score"].default
    assert default is None


async def test_dimension_mismatch_and_provider_failure(
    article_service: ArticleService,
    company_a: Company,
    employee_a: Employee,
) -> None:
    await _publish(article_service, company_a, title="Emb", body="check")
    bad_dim = KnowledgeRetriever(
        uow_factory=_uow_factory,
        article_service=article_service,
        embedding_provider=FakeEmbeddingProvider(dimension=4),
    )
    with pytest.raises(ValidationError, match="embedding dimension mismatch"):
        await bad_dim.retrieve(
            "check",
            actor_company_id=company_a.id,
            actor_employee_id=employee_a.id,
            actor_role=EmployeeRole.EMPLOYEE.value,
        )

    boom = KnowledgeRetriever(
        uow_factory=_uow_factory,
        article_service=article_service,
        embedding_provider=_BoomEmbeddings(),  # type: ignore[arg-type]
    )
    with pytest.raises(RuntimeError, match="embedding backend down"):
        await boom.retrieve(
            "check",
            actor_company_id=company_a.id,
            actor_employee_id=employee_a.id,
            actor_role=EmployeeRole.EMPLOYEE.value,
        )


async def test_super_admin_without_impersonation_is_forbidden(
    retriever: KnowledgeRetriever,
    company_a: Company,
) -> None:
    with pytest.raises(ForbiddenError, match="impersonation"):
        await retriever.retrieve(
            "anything",
            actor_company_id=company_a.id,
            actor_employee_id=uuid4(),
            actor_role=PlatformRole.SUPER_ADMIN.value,
        )


async def test_claimed_foreign_company_id_is_not_found(
    retriever: KnowledgeRetriever,
    company_a: Company,
    company_b: Company,
    employee_a: Employee,
) -> None:
    with pytest.raises(NotFoundError, match="not found"):
        await retriever.retrieve(
            "anything",
            actor_company_id=company_a.id,
            actor_employee_id=employee_a.id,
            actor_role=EmployeeRole.EMPLOYEE.value,
            claimed_company_id=company_b.id,
        )


async def test_no_public_retrieval_search_http_api() -> None:
    from app.main import app

    paths = " ".join(app.openapi()["paths"])
    assert "/ai/search" not in paths
    assert "/rag/query" not in paths
    assert "/api/v1/ai/chat" in paths


async def test_hit_contract_has_citation_fields_not_embeddings(
    article_service: ArticleService,
    retriever: KnowledgeRetriever,
    company_a: Company,
    employee_a: Employee,
) -> None:
    article = await _publish(
        article_service, company_a, title="Cite me", body="citation source"
    )
    hits = await retriever.retrieve(
        "citation source",
        actor_company_id=company_a.id,
        actor_employee_id=employee_a.id,
        actor_role=EmployeeRole.EMPLOYEE.value,
    )
    assert hits
    hit = hits[0]
    assert hit.chunk_id
    assert hit.article_id == article.id
    assert hit.version_id == article.current_version_id
    assert hit.chunk_index >= 0
    assert hit.article_title == "Cite me"
    assert hit.content
    assert 0.0 <= hit.score <= 1.0
    assert not hasattr(hit, "embedding")
    assert "embedding" not in hit.__dataclass_fields__

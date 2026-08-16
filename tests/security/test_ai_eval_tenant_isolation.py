"""AI-7 evaluation must keep AI_RETRIEVAL_ACCESS <= EXISTING_KB_ACCESS."""

from __future__ import annotations

import pytest

from app.db.enums import EmployeeRole
from app.db.models.company import Company
from app.db.models.employee import Employee
from app.services.ai.embeddings import FakeEmbeddingProvider
from app.services.ai.eval_corpus import EVAL_ARTICLES
from app.services.ai.eval_runner import seed_eval_articles, seed_program_hidden_article
from app.services.ai.indexer import KnowledgeChunkIndexer
from app.services.ai.retriever import KnowledgeRetriever
from app.services.knowledge.article_service import ArticleService
from tests.conftest import _uow_factory


class _CountingArticleService(ArticleService):
    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.list_calls = 0

    async def list_articles(self, *args, **kwargs):
        self.list_calls += 1
        return await super().list_articles(*args, **kwargs)


@pytest.fixture
def eval_acl_stack() -> tuple[_CountingArticleService, KnowledgeRetriever]:
    provider = FakeEmbeddingProvider()
    indexer = KnowledgeChunkIndexer(
        uow_factory=_uow_factory,
        embedding_provider=provider,
    )
    service = _CountingArticleService(uow_factory=_uow_factory, chunk_indexer=indexer)
    retriever = KnowledgeRetriever(
        uow_factory=_uow_factory,
        article_service=service,
        embedding_provider=provider,
    )
    return service, retriever


async def test_eval_retrieve_uses_article_service_and_blocks_company_b(
    eval_acl_stack: tuple[_CountingArticleService, KnowledgeRetriever],
    company_a: Company,
    company_b: Company,
    employee_a: Employee,
) -> None:
    service, retriever = eval_acl_stack
    seeded = await seed_eval_articles(
        service,
        company_a=company_a,
        company_b=company_b,
        articles=EVAL_ARTICLES,
    )
    foreign = seeded.keys_to_ids["bonus-b-en"]
    hits = await retriever.retrieve(
        "Company B pays an annual bonus equal to 18 percent of base salary",
        actor_company_id=employee_a.company_id,
        actor_employee_id=employee_a.id,
        actor_role=EmployeeRole.EMPLOYEE.value,
        top_k=10,
    )
    assert service.list_calls >= 1
    assert all(hit.article_id != foreign for hit in hits)
    listed = await service.list_articles(
        company_a.id,
        actor_company_id=company_a.id,
        actor_role=EmployeeRole.EMPLOYEE.value,
        actor_employee_id=employee_a.id,
        limit=1000,
    )
    allowed = {article.id for article in listed}
    assert foreign not in allowed
    assert all(hit.article_id in allowed for hit in hits)


async def test_eval_employee_cannot_retrieve_unassigned_program_article(
    eval_acl_stack: tuple[_CountingArticleService, KnowledgeRetriever],
    company_a: Company,
    employee_a: Employee,
    hr_a: Employee,
) -> None:
    service, retriever = eval_acl_stack
    hidden_id = await seed_program_hidden_article(service, company=company_a)
    employee_hits = await retriever.retrieve(
        "Executive cash bonus bands are confidential to assigned program members",
        actor_company_id=employee_a.company_id,
        actor_employee_id=employee_a.id,
        actor_role=EmployeeRole.EMPLOYEE.value,
        top_k=10,
    )
    assert all(hit.article_id != hidden_id for hit in employee_hits)
    listed = await service.list_articles(
        company_a.id,
        actor_company_id=company_a.id,
        actor_role=EmployeeRole.EMPLOYEE.value,
        actor_employee_id=employee_a.id,
        limit=1000,
    )
    assert hidden_id not in {article.id for article in listed}
    hr_listed = await service.list_articles(
        company_a.id,
        actor_company_id=company_a.id,
        actor_role=hr_a.role,
        actor_employee_id=hr_a.id,
        limit=1000,
    )
    assert hidden_id in {article.id for article in hr_listed}

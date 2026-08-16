"""Run AI-8 end-to-end RAG evaluation through production AIChatService.

Does not bypass ArticleService, RLS, or create an evaluation-only ACL path.
Does not change retrieval, prompts, top_k, or min_score.
"""

from __future__ import annotations

import time
from uuid import UUID, uuid4

from app.core.ai_constants import DEFAULT_RETRIEVAL_TOP_K
from app.core.exceptions import NotFoundError
from app.db.enums import EmployeeRole
from app.db.models.company import Company
from app.db.models.employee import Employee
from app.services.ai.chat import AIChatService, ChatAnswer
from app.services.ai.eval_runner import SeededCorpus, seed_eval_articles
from app.services.ai.llm import LLMProvider
from app.services.ai.rag_eval import (
    RagEvalReport,
    SecurityCheck,
    build_rag_report,
    load_rag_eval_dataset,
    score_case,
)
from app.services.ai.retriever import KnowledgeRetriever, RetrievalHit
from app.services.knowledge.article_service import ArticleService


def _keys_from_ids(ids: list[UUID], seeded: SeededCorpus) -> tuple[str, ...]:
    keys: list[str] = []
    seen: set[str] = set()
    for article_id in ids:
        key = seeded.ids_to_keys.get(article_id)
        if key and key not in seen:
            seen.add(key)
            keys.append(key)
    return tuple(keys)


def _hit_keys(hits: list[RetrievalHit], seeded: SeededCorpus) -> tuple[str, ...]:
    return _keys_from_ids([hit.article_id for hit in hits], seeded)


def _citation_keys(answer: ChatAnswer, seeded: SeededCorpus) -> tuple[str, ...]:
    return _keys_from_ids([item.article_id for item in answer.citations], seeded)


def collect_findings(report: RagEvalReport) -> tuple[str, ...]:
    notes: list[str] = []
    na = report.no_answer
    if na.fn:
        notes.append(
            f"{na.fn} unanswerable questions received an answer (false-negative "
            "no-answer). Without a production min_score, nearest-neighbor hits "
            "still reach the LLM."
        )
    if na.fp:
        notes.append(
            f"{na.fp} answerable questions returned no-answer (false-positive "
            "abstention), usually because retrieval returned no hits."
        )
    if report.retrieval_recall_at_k is not None and report.retrieval_recall_at_k < 0.6:
        notes.append(
            f"Recall@{report.top_k} is {_fmt(report.retrieval_recall_at_k)} on this "
            "dataset. Fake hash embeddings are not a semantic quality signal."
        )
    if report.answer.correct == 0:
        notes.append(
            "No case scored fully correct on required facts. FakeLLM is a "
            "citation stub; live OpenAI is required for factual-answer measurement."
        )
    leaked = [item.case_id for item in report.cases if item.leaked_forbidden]
    if leaked:
        notes.append(f"Forbidden-tenant strings leaked in cases: {', '.join(leaked)}")
    if not report.security_passed:
        notes.append("One or more security checks failed.")
    return tuple(notes)


def _fmt(value: float) -> str:
    return f"{value:.3f}"


async def _run_security_checks(
    *,
    chat: AIChatService,
    retriever: KnowledgeRetriever,
    seeded: SeededCorpus,
    employee_a: Employee,
    peer: Employee,
    employee_b: Employee,
) -> list[SecurityCheck]:
    checks: list[SecurityCheck] = []
    owned = await chat.answer(
        "How do visitors get on guest Wi-Fi?",
        actor_company_id=employee_a.company_id,
        actor_employee_id=employee_a.id,
        actor_role=EmployeeRole.EMPLOYEE.value,
    )
    try:
        await chat.answer(
            "follow-up",
            actor_company_id=peer.company_id,
            actor_employee_id=peer.id,
            actor_role=EmployeeRole.EMPLOYEE.value,
            conversation_id=owned.conversation_id,
        )
        checks.append(
            SecurityCheck(
                "same-tenant foreign conversation_id",
                False,
                "peer employee continued another employee's conversation",
            )
        )
    except NotFoundError:
        checks.append(
            SecurityCheck(
                "same-tenant foreign conversation_id",
                True,
                "peer employee received NotFoundError",
            )
        )

    try:
        await chat.answer(
            "follow-up",
            actor_company_id=employee_b.company_id,
            actor_employee_id=employee_b.id,
            actor_role=EmployeeRole.EMPLOYEE.value,
            conversation_id=owned.conversation_id,
        )
        checks.append(
            SecurityCheck(
                "cross-tenant conversation_id",
                False,
                "tenant B continued tenant A's conversation",
            )
        )
    except NotFoundError:
        checks.append(
            SecurityCheck(
                "cross-tenant conversation_id",
                True,
                "tenant B received NotFoundError",
            )
        )

    unknown = uuid4()
    try:
        await chat.answer(
            "follow-up",
            actor_company_id=employee_a.company_id,
            actor_employee_id=employee_a.id,
            actor_role=EmployeeRole.EMPLOYEE.value,
            conversation_id=unknown,
        )
        checks.append(
            SecurityCheck(
                "unknown conversation_id",
                False,
                "unknown conversation_id was accepted",
            )
        )
    except NotFoundError:
        checks.append(
            SecurityCheck(
                "unknown conversation_id",
                True,
                "unknown conversation_id returned NotFoundError",
            )
        )

    hits = await retriever.retrieve(
        "What is Company B annual bonus formula and the Northwind Q4 target payout?",
        actor_company_id=employee_a.company_id,
        actor_employee_id=employee_a.id,
        actor_role=EmployeeRole.EMPLOYEE.value,
        top_k=DEFAULT_RETRIEVAL_TOP_K,
    )
    leaked_ids = [hit.article_id for hit in hits if hit.article_id in seeded.foreign_ids]
    checks.append(
        SecurityCheck(
            "cross-tenant knowledge retrieval",
            not leaked_ids,
            (
                "Company B article ids absent from Company A hits"
                if not leaked_ids
                else f"leaked {len(leaked_ids)} foreign article id(s)"
            ),
        )
    )
    return checks


async def run_rag_evaluation(
    *,
    article_service: ArticleService,
    retriever: KnowledgeRetriever,
    chat: AIChatService,
    llm: LLMProvider,
    company_a: Company,
    company_b: Company,
    employee_a: Employee,
    peer: Employee,
    employee_b: Employee,
    embedding_provider: str,
    live_openai: bool,
) -> tuple[RagEvalReport, SeededCorpus]:
    dataset = load_rag_eval_dataset()
    seeded = await seed_eval_articles(
        article_service,
        company_a=company_a,
        company_b=company_b,
    )
    scored = []
    for spec in dataset:
        hits = await retriever.retrieve(
            spec.question,
            actor_company_id=employee_a.company_id,
            actor_employee_id=employee_a.id,
            actor_role=EmployeeRole.EMPLOYEE.value,
            top_k=DEFAULT_RETRIEVAL_TOP_K,
        )
        started = time.perf_counter()
        answer = await chat.answer(
            spec.question,
            actor_company_id=employee_a.company_id,
            actor_employee_id=employee_a.id,
            actor_role=EmployeeRole.EMPLOYEE.value,
        )
        latency_ms = (time.perf_counter() - started) * 1000
        scored.append(
            score_case(
                spec,
                retrieved_keys=_hit_keys(hits, seeded),
                cited_keys=_citation_keys(answer, seeded),
                answer=answer.answer,
                no_answer=answer.no_answer,
                latency_ms=latency_ms,
            )
        )
    security = await _run_security_checks(
        chat=chat,
        retriever=retriever,
        seeded=seeded,
        employee_a=employee_a,
        peer=peer,
        employee_b=employee_b,
    )
    draft = build_rag_report(
        cases=scored,
        dataset=dataset,
        security=security,
        live_openai=live_openai,
        embedding_provider=embedding_provider,
        llm_provider="openai" if live_openai else "fake",
        llm_model=llm.model,
    )
    findings = collect_findings(draft)
    report = build_rag_report(
        cases=scored,
        dataset=dataset,
        security=security,
        live_openai=live_openai,
        embedding_provider=embedding_provider,
        llm_provider="openai" if live_openai else "fake",
        llm_model=llm.model,
        findings=findings,
        measured_at=draft.measured_at,
    )
    return report, seeded

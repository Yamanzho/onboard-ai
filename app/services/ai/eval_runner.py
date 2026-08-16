"""Run AI-7 retrieval evaluation through the production KnowledgeRetriever.

Does not bypass ArticleService, RLS, or create an evaluation-only ACL path.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from uuid import UUID

from app.core.ai_constants import (
    DEFAULT_CHUNK_OVERLAP_CHARS,
    MAX_CHUNKS_PER_ARTICLE,
    SMALL_ARTICLE_CHARS,
)
from app.db.enums import EmployeeRole, KnowledgeVisibility
from app.db.models.company import Company
from app.db.models.employee import Employee
from app.services.ai.chunking import chunk_article, extract_index_text
from app.services.ai.eval_corpus import (
    CHUNKING_HTML_RU,
    CHUNKING_KK_BULLETS,
    COMPANY_A,
    COMPANY_B,
    EVAL_ARTICLES,
    EVAL_CASES,
    EvalArticle,
    EvalCase,
)
from app.services.ai.evaluation import (
    EVAL_TOP_KS,
    CaseOutcome,
    EvaluationReport,
    article_in_top_k,
    build_report,
    chunk_index_in_top_k,
)
from app.services.ai.retriever import KnowledgeRetriever, RetrievalHit
from app.services.knowledge.article_service import ArticleService

MAX_EVAL_TOP_K = max(EVAL_TOP_KS)
PRIMARY_FROM_HITS = 5


@dataclass
class SeededCorpus:
    keys_to_ids: dict[str, UUID]
    ids_to_keys: dict[UUID, str]
    version_ids: dict[str, UUID]
    foreign_ids: frozenset[UUID]


async def seed_eval_articles(
    article_service: ArticleService,
    *,
    company_a: Company,
    company_b: Company,
    articles: tuple[EvalArticle, ...] = EVAL_ARTICLES,
) -> SeededCorpus:
    companies = {COMPANY_A: company_a, COMPANY_B: company_b}
    keys_to_ids: dict[str, UUID] = {}
    ids_to_keys: dict[UUID, str] = {}
    version_ids: dict[str, UUID] = {}
    foreign_ids: set[UUID] = set()
    for spec in articles:
        company = companies[spec.company]
        created = await article_service.create_article(
            company_id=company.id,
            actor_company_id=company.id,
            title=spec.title,
            body=spec.body,
            body_format=spec.body_format,
            visibility=spec.visibility,
        )
        published = await article_service.publish_article(
            created.id,
            company_id=company.id,
        )
        keys_to_ids[spec.key] = published.id
        ids_to_keys[published.id] = spec.key
        assert published.current_version_id is not None
        version_ids[spec.key] = published.current_version_id
        if spec.company == COMPANY_B:
            foreign_ids.add(published.id)
    return SeededCorpus(
        keys_to_ids=keys_to_ids,
        ids_to_keys=ids_to_keys,
        version_ids=version_ids,
        foreign_ids=frozenset(foreign_ids),
    )


def _keys_to_ids(keys: tuple[str, ...], seeded: SeededCorpus) -> tuple[UUID, ...]:
    return tuple(seeded.keys_to_ids[key] for key in keys)


def outcome_from_hits(
    case: EvalCase,
    hits: list[RetrievalHit],
    seeded: SeededCorpus,
) -> CaseOutcome:
    expected_ids = _keys_to_ids(case.expected_keys, seeded)
    hit_ids = tuple(hit.article_id for hit in hits)
    hit_keys = tuple(seeded.ids_to_keys.get(article_id, article_id.hex) for article_id in hit_ids)
    scores = tuple(hit.score for hit in hits)
    article_hit_at = {
        k: article_in_top_k(hits, expected_ids, k) for k in EVAL_TOP_KS
    }
    chunk_hit: bool | None = None
    if case.expected_chunk_index is not None:
        chunk_hit = chunk_index_in_top_k(
            hits,
            expected_ids,
            chunk_index=case.expected_chunk_index,
            k=PRIMARY_FROM_HITS,
        )
    leaked = any(article_id in seeded.foreign_ids for article_id in hit_ids)
    expected_set = set(expected_ids)
    match_score = next(
        (hit.score for hit in hits if hit.article_id in expected_set),
        None,
    )
    if case.expect_no_answer:
        wrong_top = bool(hits)
    else:
        wrong_top = bool(hits) and hits[0].article_id not in expected_set
    return CaseOutcome(
        case_id=case.id,
        question=case.question,
        language=case.language,
        cross_language=case.cross_language,
        expect_no_answer=case.expect_no_answer,
        expected_keys=case.expected_keys,
        expected_article_ids=expected_ids,
        hit_keys=hit_keys,
        hit_article_ids=hit_ids,
        scores=scores,
        top_score=scores[0] if scores else None,
        exact_phrase=case.exact_phrase,
        article_hit_at=article_hit_at,
        expected_chunk_index=case.expected_chunk_index,
        chunk_index_hit=chunk_hit,
        leaked_foreign_article=leaked,
        target_language=case.target_language,
        match_score=match_score,
        wrong_top=wrong_top,
    )


async def evaluate_cases(
    retriever: KnowledgeRetriever,
    *,
    actor: Employee,
    seeded: SeededCorpus,
    cases: tuple[EvalCase, ...] = EVAL_CASES,
    actor_role: str | None = None,
) -> list[CaseOutcome]:
    role = actor_role or actor.role
    outcomes: list[CaseOutcome] = []
    for case in cases:
        hits = await retriever.retrieve(
            case.question,
            actor_company_id=actor.company_id,
            actor_employee_id=actor.id,
            actor_role=role,
            top_k=MAX_EVAL_TOP_K,
        )
        outcomes.append(outcome_from_hits(case, hits, seeded))
    return outcomes


def evaluate_chunking_offline() -> dict[str, Any]:
    """Chunker checks that do not touch the retriever or ACL."""
    results: dict[str, Any] = {}
    fixtures = [
        *[article for article in EVAL_ARTICLES if article.chunking],
        CHUNKING_HTML_RU,
        CHUNKING_KK_BULLETS,
    ]
    failures: list[str] = []
    for spec in fixtures:
        chunks = chunk_article(
            title=spec.title,
            body=spec.body,
            body_format=spec.body_format,
        )
        title_n, body_n = extract_index_text(
            title=spec.title,
            body=spec.body,
            body_format=spec.body_format,
        )
        if not chunks:
            failures.append(f"{spec.key}: empty chunks")
            continue
        if any(not chunk.strip() for chunk in chunks):
            failures.append(f"{spec.key}: blank chunk")
        if not all(chunk.startswith(title_n) for chunk in chunks if title_n):
            failures.append(f"{spec.key}: missing title prefix")
        if len(chunks) > MAX_CHUNKS_PER_ARTICLE:
            failures.append(f"{spec.key}: too many chunks")
        joined = "\n".join(chunks)
        if spec.language == "kk" and "қ" not in spec.title + spec.body:
            pass
        for marker in _unicode_markers(spec):
            if marker not in joined and marker not in title_n:
                failures.append(f"{spec.key}: unicode missing {marker!r}")
        if spec.chunking == "short":
            if len(title_n) + 2 + len(body_n) > SMALL_ARTICLE_CHARS:
                failures.append(f"{spec.key}: expected short article")
            if len(chunks) != 1:
                failures.append(f"{spec.key}: short article must be 1 chunk")
        if spec.chunking == "long" and len(chunks) < 2:
            failures.append(f"{spec.key}: long article should split")
        if spec.chunking == "html":
            if "<p>" in joined or "<script>" in joined.lower():
                failures.append(f"{spec.key}: html tags leaked")
        missing = _missing_body_tokens(body_n, joined)
        if missing:
            failures.append(f"{spec.key}: content loss {missing[:5]!r}")
        if len(chunks) > 1:
            overlap_ok = _has_overlap(chunks, title_n)
            if not overlap_ok:
                failures.append(f"{spec.key}: no overlap between windows")
        results[spec.key] = {
            "chunk_count": len(chunks),
            "title_prefix": all(chunk.startswith(title_n) for chunk in chunks if title_n),
        }
    results["failures"] = failures
    results["overlap_chars"] = DEFAULT_CHUNK_OVERLAP_CHARS
    results["passed"] = not failures
    return results


def _unicode_markers(spec: EvalArticle) -> tuple[str, ...]:
    text = spec.title + spec.body
    markers = []
    for char in ("ё", "ъ", "қ", "ғ", "ң", "ө", "ү", "ә", "і", "һ"):
        if char in text:
            markers.append(char)
    return tuple(markers)


def _missing_body_tokens(body: str, joined_chunks: str) -> list[str]:
    tokens = [token for token in body.replace("#", " ").split() if len(token) >= 4]
    missing: list[str] = []
    for token in tokens:
        cleaned = token.strip(".,;:!?*-|")
        if len(cleaned) < 4:
            continue
        if cleaned not in joined_chunks:
            missing.append(cleaned)
    return missing


def _has_overlap(chunks: list[str], title: str) -> bool:
    prefix = f"{title}\n\n" if title else ""
    bodies = []
    for chunk in chunks:
        body = chunk[len(prefix) :] if prefix and chunk.startswith(prefix) else chunk
        bodies.append(body)
    for left, right in zip(bodies, bodies[1:], strict=False):
        window = min(DEFAULT_CHUNK_OVERLAP_CHARS, len(left), len(right))
        if window < 8:
            continue
        if left[-window:] in right or any(
            token in right for token in left.split()[-6:] if len(token) >= 4
        ):
            return True
    return len(bodies) < 2


async def run_retrieval_evaluation(
    *,
    article_service: ArticleService,
    retriever: KnowledgeRetriever,
    company_a: Company,
    company_b: Company,
    employee_a: Employee,
    provider_name: str,
    live_openai: bool,
    model: str = "",
    dimension: int = 1536,
    cache_hits: int = 0,
    network_batches: int = 0,
    embedded_texts: int = 0,
) -> tuple[EvaluationReport, SeededCorpus]:
    seeded = await seed_eval_articles(
        article_service,
        company_a=company_a,
        company_b=company_b,
    )
    outcomes = await evaluate_cases(
        retriever,
        actor=employee_a,
        seeded=seeded,
        actor_role=EmployeeRole.EMPLOYEE.value,
    )
    chunking = evaluate_chunking_offline()
    report = build_report(
        provider_name=provider_name,
        live_openai=live_openai,
        outcomes=outcomes,
        chunking=chunking,
        model=model or provider_name,
        dimension=dimension,
        cache_hits=cache_hits,
        network_batches=network_batches,
        embedded_texts=embedded_texts,
    )
    return report, seeded


async def seed_program_hidden_article(
    article_service: ArticleService,
    *,
    company: Company,
) -> UUID:
    created = await article_service.create_article(
        company_id=company.id,
        actor_company_id=company.id,
        title="Executive compensation bands",
        body=(
            "Executive cash bonus bands are confidential to assigned program "
            "members. This article must not be retrievable by a regular employee."
        ),
        visibility=KnowledgeVisibility.PROGRAM.value,
    )
    published = await article_service.publish_article(created.id, company_id=company.id)
    return published.id

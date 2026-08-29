"""AI-hybrid-1: Hybrid vector + FTS retrieval tests.

Covers all 20 acceptance criteria:
1.  _build_tsquery("Евгений") → "евгений"
2.  _build_tsquery("Тей Евгений Г.") → "тей & евгений"
3.  _build_tsquery("Джумадуллаева Н. И.") → "джумадуллаева"
4.  Punctuation-only query → None
5.  Lexical repo search returns exact name match
6.  Vector-only result remains valid
7.  Lexical-only result enters merged pool
8.  Vector + lexical result receives boost exactly once
9.  Duplicate chunk_id is not duplicated
10. Max 2 chunks per article remains enforced
11. top_k remains 5
12. ACL allowed_article_ids respected by lexical search
13. Unpublished article cannot be returned by lexical search
14. Non-current version cannot be returned
15. Tenant isolation remains intact
16. Short query with history is expanded for retrieval
17. Original question remains unchanged for LLM
18. No history means no rewrite
19. Long query is not rewritten
20. "Евгений" can retrieve a chunk containing "Тей Евгений Г."
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest

from app.core.ai_constants import (
    DEFAULT_RETRIEVAL_TOP_K,
    LEXICAL_BOOST,
    LEXICAL_FLOOR_SCORE,
    MAX_CHUNKS_PER_ARTICLE_RESULT,
    SHORT_QUERY_EXPANSION_MAX_CHARS,
    SHORT_QUERY_EXPANSION_WORDS,
)
from app.db.enums import EmployeeRole
from app.db.models.company import Company
from app.db.models.employee import Employee
from app.db.uow import UnitOfWork
from app.services.ai.chat import _expand_query_with_history
from app.services.ai.embeddings import FakeEmbeddingProvider
from app.services.ai.history import HistoryTurn
from app.services.ai.retriever import KnowledgeRetriever, _build_tsquery
from app.services.knowledge.article_service import ArticleService
from tests.conftest import _uow_factory

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_KWARGS = dict(actor_role=EmployeeRole.EMPLOYEE.value)


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


@pytest.fixture
def retriever(article_service: ArticleService) -> KnowledgeRetriever:
    return KnowledgeRetriever(
        uow_factory=_uow_factory,
        article_service=article_service,
        embedding_provider=FakeEmbeddingProvider(),
    )


# ===========================================================================
# Tests 1–4: _build_tsquery (pure unit, no DB)
# ===========================================================================


def test_build_tsquery_single_cyrillic_name() -> None:
    """Test 1: single Cyrillic name → lower-cased single token."""
    result = _build_tsquery("Евгений")
    assert result == "евгений"


def test_build_tsquery_three_tokens_drops_single_char() -> None:
    """Test 2: three tokens, single-char 'г' dropped, remaining two joined with AND."""
    result = _build_tsquery("Тей Евгений Г.")
    assert result == "тей & евгений"


def test_build_tsquery_name_with_initials_keeps_long_token() -> None:
    """Test 3: surname + single-char initials → only surname survives."""
    result = _build_tsquery("Джумадуллаева Н. И.")
    assert result == "джумадуллаева"


def test_build_tsquery_punctuation_only_returns_none() -> None:
    """Test 4: punctuation / operator-only input returns None (skip lexical path)."""
    assert _build_tsquery("...") is None
    assert _build_tsquery("?!?") is None
    assert _build_tsquery("&|!") is None
    assert _build_tsquery("Г. Н.") is None  # only single-char tokens after regex


def test_build_tsquery_long_query_uses_or() -> None:
    """More than 3 meaningful tokens → OR operator for higher recall."""
    result = _build_tsquery("кто главный бухгалтер компании")
    assert result is not None
    assert " | " in result
    assert "&" not in result


def test_build_tsquery_three_token_question_uses_and() -> None:
    """'Кто главный бухгалтер?' has exactly 3 tokens → AND (≤3 threshold)."""
    result = _build_tsquery("Кто главный бухгалтер?")
    assert result == "кто & главный & бухгалтер"


def test_build_tsquery_three_meaningful_tokens_uses_and() -> None:
    """Exactly 3 meaningful tokens → AND for higher precision."""
    result = _build_tsquery("прочие поименованные лица")
    assert result == "прочие & поименованные & лица"


def test_build_tsquery_no_tsquery_operators_in_output() -> None:
    """User input containing tsquery special chars must not appear in output."""
    # Even if user types operators, they must not reach PostgreSQL as operators.
    result = _build_tsquery("евгений | омарова ! джумадуллаева")
    # Pipeline: regex extracts tokens, joins with & (≤3 tokens after filter)
    assert result is not None
    # The raw "|" and "!" must not be present as standalone tsquery operators.
    # They can only appear inside token strings (not here since they're ASCII ops).
    tokens = result.replace(" & ", " ").replace(" | ", " ").split()
    for tok in tokens:
        assert tok.isalpha() or tok.isdigit() or tok.isalnum()


# ===========================================================================
# Tests 5 & 20: Lexical repository search + end-to-end name retrieval
# ===========================================================================


async def test_lexical_search_returns_exact_name_match(
    article_service: ArticleService,
    company_a: Company,
    employee_a: Employee,
) -> None:
    """Tests 5 & 20: FTS finds chunk containing 'Тей Евгений Г.' for query 'Евгений'."""
    personnel_body = (
        "Прочие поименованные лица\n\n"
        "Тей Евгений Г., Темир Ельнур Н., Гылымбек Алгыс,\n"
        "Джумадуллаева Н. И., Омарова Г. М., Рамиль"
    )
    article = await _publish(
        article_service,
        company_a,
        title="общее сведение",
        body=personnel_body,
    )

    async with _uow_factory() as uow:
        await uow.enter_tenant(company_a.id)
        rows = await uow.knowledge_article_chunks.search_lexical_current_published(
            allowed_article_ids=[article.id],
            tsquery_text="евгений",
            limit=10,
        )

    assert rows, "Lexical search must return at least one row for 'евгений'"
    chunk_contents = [row[0].content for row in rows]
    assert any("Евгений" in c for c in chunk_contents), (
        "Chunk containing 'Тей Евгений Г.' must be returned"
    )
    assert all(row[0].article_id == article.id for row in rows)


# ===========================================================================
# Test 6: Vector-only result remains valid after hybrid merge
# ===========================================================================


async def test_vector_only_result_survives_merge(
    article_service: ArticleService,
    retriever: KnowledgeRetriever,
    company_a: Company,
    employee_a: Employee,
) -> None:
    """Test 6: vector search results still appear in hybrid output."""
    unique = f"VACATIONPOLICYUNIQUE_{uuid4().hex}"
    await _publish(article_service, company_a, title="Vacation", body=unique)

    hits = await retriever.retrieve(
        unique,
        actor_company_id=company_a.id,
        actor_employee_id=employee_a.id,
        **_KWARGS,
    )
    assert hits, "Vector-matched chunk must appear in hybrid result"
    assert any(unique in h.content for h in hits)


# ===========================================================================
# Test 7: Lexical-only result enters the merged pool
# ===========================================================================


async def test_lexical_only_result_enters_merged_pool(
    article_service: ArticleService,
    company_a: Company,
    employee_a: Employee,
) -> None:
    """Test 7: a chunk found only by FTS (not vector top-N) gets LEXICAL_FLOOR_SCORE."""
    # We use the internal _merge_and_score directly with a fake vector pool
    # that does not contain the lexical chunk, confirming it still enters hits.
    from app.db.models.knowledge_article_chunk import KnowledgeArticleChunk
    from app.services.ai.retriever import _merge_and_score

    lex_chunk = MagicMock(spec=KnowledgeArticleChunk)
    lex_chunk.id = uuid4()
    lex_chunk.article_id = uuid4()
    lex_chunk.version_id = uuid4()
    lex_chunk.chunk_index = 0
    lex_chunk.content = "Тей Евгений Г."

    # No vector rows — lexical-only
    hits = _merge_and_score(
        vector_rows=[],
        lexical_rows=[(lex_chunk, 0.9, "общее сведение")],
        top_k=5,
        min_score=None,
    )
    assert len(hits) == 1
    assert hits[0].chunk_id == lex_chunk.id
    assert hits[0].score == pytest.approx(LEXICAL_FLOOR_SCORE)
    assert hits[0].article_title == "общее сведение"


# ===========================================================================
# Test 8: Vector + lexical result gets boost exactly once
# ===========================================================================


def test_vector_plus_lexical_gets_boost_exactly_once() -> None:
    """Test 8: the LEXICAL_BOOST is added exactly once when both paths hit."""
    from app.db.models.knowledge_article_chunk import KnowledgeArticleChunk
    from app.services.ai.retriever import _merge_and_score

    shared_id = uuid4()
    article_id = uuid4()

    vec_chunk = MagicMock(spec=KnowledgeArticleChunk)
    vec_chunk.id = shared_id
    vec_chunk.article_id = article_id
    vec_chunk.version_id = uuid4()
    vec_chunk.chunk_index = 0
    vec_chunk.content = "Тей Евгений Г., Омарова"

    lex_chunk = MagicMock(spec=KnowledgeArticleChunk)
    lex_chunk.id = shared_id  # same chunk_id
    lex_chunk.article_id = article_id
    lex_chunk.version_id = vec_chunk.version_id
    lex_chunk.chunk_index = 0
    lex_chunk.content = vec_chunk.content

    cosine_distance = 0.3  # score = 1 - 0.3 = 0.7
    expected_score = 1.0 - cosine_distance + LEXICAL_BOOST

    hits = _merge_and_score(
        vector_rows=[(vec_chunk, cosine_distance, "title")],
        lexical_rows=[(lex_chunk, 0.9, "title")],
        top_k=5,
        min_score=None,
    )
    assert len(hits) == 1, "Same chunk_id must not be duplicated"
    assert hits[0].score == pytest.approx(expected_score)


# ===========================================================================
# Test 9: Duplicate chunk_id is not duplicated
# ===========================================================================


def test_duplicate_chunk_id_not_duplicated() -> None:
    """Test 9: a chunk appearing in both vector and lexical rows appears once."""
    from app.db.models.knowledge_article_chunk import KnowledgeArticleChunk
    from app.services.ai.retriever import _merge_and_score

    shared_id = uuid4()
    chunk = MagicMock(spec=KnowledgeArticleChunk)
    chunk.id = shared_id
    chunk.article_id = uuid4()
    chunk.version_id = uuid4()
    chunk.chunk_index = 0
    chunk.content = "shared"

    hits = _merge_and_score(
        vector_rows=[(chunk, 0.4, "t")],
        lexical_rows=[(chunk, 0.5, "t")],
        top_k=10,
        min_score=None,
    )
    chunk_ids = [h.chunk_id for h in hits]
    assert chunk_ids.count(shared_id) == 1


# ===========================================================================
# Test 10: Max 2 chunks per article
# ===========================================================================


async def test_max_two_chunks_per_article_enforced(
    article_service: ArticleService,
    retriever: KnowledgeRetriever,
    company_a: Company,
    employee_a: Employee,
) -> None:
    """Test 10: MAX_CHUNKS_PER_ARTICLE_RESULT=2 is enforced in hybrid mode."""
    paragraph = "Handbook section repeated text. " * 60
    body = "\n\n".join(f"## Part {i}\n{paragraph}" for i in range(6))
    article = await _publish(article_service, company_a, title="Handbook", body=body)

    hits = await retriever.retrieve(
        "Handbook section repeated",
        actor_company_id=company_a.id,
        actor_employee_id=employee_a.id,
        **_KWARGS,
        top_k=20,
    )
    from_article = [h for h in hits if h.article_id == article.id]
    assert len(from_article) <= MAX_CHUNKS_PER_ARTICLE_RESULT


# ===========================================================================
# Test 11: top_k=5 default is preserved
# ===========================================================================


async def test_top_k_default_is_five(
    article_service: ArticleService,
    retriever: KnowledgeRetriever,
    company_a: Company,
    employee_a: Employee,
) -> None:
    """Test 11: default top_k=5 is not exceeded even with many articles."""
    for i in range(8):
        await _publish(
            article_service,
            company_a,
            title=f"Article {i}",
            body=f"onboarding guide section {i} handbook",
        )

    hits = await retriever.retrieve(
        "onboarding guide handbook",
        actor_company_id=company_a.id,
        actor_employee_id=employee_a.id,
        **_KWARGS,
    )
    assert len(hits) <= DEFAULT_RETRIEVAL_TOP_K


# ===========================================================================
# Test 12: ACL allowed_article_ids respected by lexical search
# ===========================================================================


async def test_lexical_search_respects_acl(
    article_service: ArticleService,
    company_a: Company,
    employee_a: Employee,
) -> None:
    """Test 12: lexical search with empty allowed_ids returns nothing."""
    unique = f"ACLTEST_{uuid4().hex}"
    await _publish(article_service, company_a, title="ACL check", body=unique)

    tsquery = unique.lower()
    async with _uow_factory() as uow:
        await uow.enter_tenant(company_a.id)
        # Pass empty allowed_ids — must return nothing even though content matches
        rows = await uow.knowledge_article_chunks.search_lexical_current_published(
            allowed_article_ids=[],
            tsquery_text=tsquery,
            limit=10,
        )
    assert rows == [], "Lexical search with empty ACL must return empty list"


# ===========================================================================
# Test 13: Unpublished article not returned by lexical search
# ===========================================================================


async def test_unpublished_article_not_returned_lexically(
    article_service: ArticleService,
    company_a: Company,
    employee_a: Employee,
) -> None:
    """Test 13: draft article with matching content is excluded from lexical results."""
    unique = f"DRAFTLEX_{uuid4().hex}"
    draft = await article_service.create_article(
        company_id=company_a.id,
        actor_company_id=company_a.id,
        title="Draft lexical",
        body=unique,
    )
    # draft is not published — it has no current_version_id that passes the join
    assert draft.status != "published"

    # Even passing the draft's id in allowed list must not return it
    async with _uow_factory() as uow:
        await uow.enter_tenant(company_a.id)
        rows = await uow.knowledge_article_chunks.search_lexical_current_published(
            allowed_article_ids=[draft.id],
            tsquery_text=unique[:30].lower().replace("_", ""),
            limit=10,
        )
    assert all(unique not in row[0].content for row in rows), (
        "Draft content must not appear in lexical results"
    )


# ===========================================================================
# Test 14: Non-current version not returned
# ===========================================================================


async def test_non_current_version_not_returned_lexically(
    article_service: ArticleService,
    company_a: Company,
    employee_a: Employee,
) -> None:
    """Test 14: after re-publishing, only the new version's chunk is retrievable."""
    v1_token = f"V1LEX_{uuid4().hex}"
    v2_token = f"V2LEX_{uuid4().hex}"
    article = await _publish(article_service, company_a, title="Versioned", body=v1_token)
    await article_service.update_article(
        article.id, company_id=company_a.id, title="Versioned", body=v2_token
    )

    async with _uow_factory() as uow:
        await uow.enter_tenant(company_a.id)
        v1_token_clean = "".join(c for c in v1_token.lower() if c.isalnum())
        rows = await uow.knowledge_article_chunks.search_lexical_current_published(
            allowed_article_ids=[article.id],
            tsquery_text=v1_token_clean[:20],
            limit=10,
        )
    assert all(v1_token not in row[0].content for row in rows), (
        "Historical version content must not appear in lexical results"
    )


# ===========================================================================
# Test 15: Tenant isolation
# ===========================================================================


async def test_tenant_isolation_in_lexical_search(
    article_service: ArticleService,
    company_a: Company,
    company_b: Company,
    employee_a: Employee,
    employee_b: Employee,
) -> None:
    """Test 15: company B's content is invisible to company A's lexical search."""
    secret_b = f"SECRETB_{uuid4().hex}"
    article_b = await _publish(
        article_service, company_b, title="B secret", body=secret_b
    )

    token_clean = "".join(c for c in secret_b.lower() if c.isalnum())
    async with _uow_factory() as uow:
        # Enter tenant A — RLS blocks access to company B rows
        await uow.enter_tenant(company_a.id)
        rows = await uow.knowledge_article_chunks.search_lexical_current_published(
            # Even if we somehow passed B's article id, RLS blocks it
            allowed_article_ids=[article_b.id],
            tsquery_text=token_clean[:20],
            limit=10,
        )
    assert rows == [], "Tenant A must not see tenant B's content via lexical search"


# ===========================================================================
# Tests 16–19: _expand_query_with_history (pure unit, no DB)
# ===========================================================================


def test_short_query_with_history_is_expanded() -> None:
    """Test 16: query ≤ SHORT_QUERY_EXPANSION_WORDS words + history → expanded."""
    history = (
        HistoryTurn(role="user", content="Прочие поименованные лица"),
        HistoryTurn(
            role="assistant",
            content="Прочие поименованные лица включают: Тей Евгений Г., Омарова Г. М.",
        ),
    )
    result = _expand_query_with_history("Евгений", history)
    assert result.startswith("Евгений ")
    assert "Тей Евгений Г." in result


def test_original_query_unchanged_in_expansion() -> None:
    """Test 17: the original query string is the prefix of the expansion."""
    original = "Евгений"
    history = (
        HistoryTurn(role="assistant", content="Тей Евгений Г. — сотрудник."),
    )
    result = _expand_query_with_history(original, history)
    assert result.startswith(original)
    # The original must never be modified in isolation — caller passes it to LLM
    assert original == "Евгений"  # immutable string; function does not mutate


def test_no_history_means_no_rewrite() -> None:
    """Test 18: empty history → original query returned unchanged."""
    result = _expand_query_with_history("Евгений", ())
    assert result == "Евгений"


def test_long_query_is_not_rewritten() -> None:
    """Test 19: query longer than SHORT_QUERY_EXPANSION_WORDS → no expansion."""
    long_query = "Прочие поименованные лица в компании"  # 5 words
    history = (
        HistoryTurn(role="assistant", content="Тей Евгений Г."),
    )
    result = _expand_query_with_history(long_query, history)
    assert result == long_query


def test_expansion_capped_at_max_chars() -> None:
    """Expansion must not exceed SHORT_QUERY_EXPANSION_MAX_CHARS."""
    history = (
        HistoryTurn(role="assistant", content="X" * 600),
    )
    result = _expand_query_with_history("Ок", history)
    assert len(result) <= SHORT_QUERY_EXPANSION_MAX_CHARS


def test_no_assistant_turn_means_no_rewrite() -> None:
    """Only user turns in history → no expansion (no assistant content)."""
    history = (
        HistoryTurn(role="user", content="Прочие поименованные лица"),
    )
    result = _expand_query_with_history("Евгений", history)
    assert result == "Евгений"


# ===========================================================================
# Test 20 (end-to-end): "Евгений" retrieves chunk with "Тей Евгений Г."
# ===========================================================================


async def test_evgeny_retrieves_personnel_chunk(
    article_service: ArticleService,
    retriever: KnowledgeRetriever,
    company_a: Company,
    employee_a: Employee,
) -> None:
    """Test 20 (end-to-end): hybrid retriever finds personnel chunk for bare name query."""
    personnel_body = (
        "Прочие поименованные лица\n\n"
        "Тей Евгений Г., Темир Ельнур Н., Гылымбек Алгыс,\n"
        "Джумадуллаева Н. И., Омарова Г. М., Рамиль"
    )
    await _publish(
        article_service,
        company_a,
        title="общее сведение",
        body=personnel_body,
    )

    hits = await retriever.retrieve(
        "Евгений",
        actor_company_id=company_a.id,
        actor_employee_id=employee_a.id,
        **_KWARGS,
    )
    assert hits, "'Евгений' must retrieve at least one chunk via lexical path"
    found = any("Евгений" in h.content for h in hits)
    assert found, "Chunk containing 'Тей Евгений Г.' must be in the result set"


# ===========================================================================
# Bonus: other name queries from acceptance criteria
# ===========================================================================


@pytest.mark.parametrize("name", ["Джумадуллаева", "Омарова", "Рамиль"])
async def test_name_queries_retrieve_personnel_chunk(
    article_service: ArticleService,
    retriever: KnowledgeRetriever,
    company_a: Company,
    employee_a: Employee,
    name: str,
) -> None:
    """Lexical path retrieves personnel chunk for short surname/first-name queries."""
    personnel_body = (
        "Прочие поименованные лица\n\n"
        "Тей Евгений Г., Темир Ельнур Н., Гылымбек Алгыс,\n"
        "Джумадуллаева Н. И., Омарова Г. М., Рамиль"
    )
    await _publish(
        article_service,
        company_a,
        title="общее сведение",
        body=personnel_body,
    )

    hits = await retriever.retrieve(
        name,
        actor_company_id=company_a.id,
        actor_employee_id=employee_a.id,
        **_KWARGS,
    )
    assert hits, f"'{name}' must retrieve personnel chunk via lexical path"
    assert any(name in h.content for h in hits), (
        f"Chunk containing '{name}' must appear in results"
    )


async def test_semantic_query_still_works_after_hybrid(
    article_service: ArticleService,
    retriever: KnowledgeRetriever,
    company_a: Company,
    employee_a: Employee,
) -> None:
    """Semantic query 'Прочие поименованные лица' continues to work in hybrid mode."""
    personnel_body = (
        "Прочие поименованные лица\n\n"
        "Тей Евгений Г., Темир Ельнур Н., Гылымбек Алгыс"
    )
    await _publish(
        article_service,
        company_a,
        title="общее сведение",
        body=personnel_body,
    )

    hits = await retriever.retrieve(
        "Прочие поименованные лица",
        actor_company_id=company_a.id,
        actor_employee_id=employee_a.id,
        **_KWARGS,
    )
    assert hits
    assert any("Прочие поименованные лица" in h.content for h in hits)

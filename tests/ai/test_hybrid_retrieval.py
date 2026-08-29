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
)
from app.db.enums import EmployeeRole
from app.db.models.company import Company
from app.db.models.employee import Employee
from app.db.uow import UnitOfWork
from app.services.ai.chat import NO_ANSWER_MESSAGE, _expand_query_with_history
from app.services.ai.embeddings import FakeEmbeddingProvider
from app.services.ai.history import HistoryTurn
from app.services.ai.retriever import KnowledgeRetriever, _build_tsquery
from app.services.knowledge.article_service import ArticleService
from tests.conftest import _create_employee, _uow_factory

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
        bare = tok.removesuffix(":*")
        assert bare.isalnum()
        assert "|" not in tok and "!" not in tok


def test_build_tsquery_hyphenated_cyrillic_uses_prefix() -> None:
    """Стоп-фактор must prefix Cyrillic hyphen parts so 'факторы' can match."""
    assert _build_tsquery("Стоп-фактор") == "стоп:* & фактор:*"


def test_build_tsquery_ai_assistant_prefixes_cyrillic_part_only() -> None:
    """AI-ассистент: Latin 'ai' stays exact; Cyrillic part is prefixed."""
    assert _build_tsquery("AI-ассистент") == "ai & ассистент:*"


def test_build_tsquery_latin_hyphen_and_plain_terms_unchanged() -> None:
    """English, numbers, and non-hyphenated Russian keep exact tokens."""
    assert _build_tsquery("CRM") == "crm"
    assert _build_tsquery("CHECKLISTS") == "checklists"
    assert _build_tsquery("Сквозной порядок") == "сквозной & порядок"
    assert _build_tsquery("P13 Доставка по РК") == "p13 | доставка | по | рк"
    assert _build_tsquery("CHECKLIST CL-PREOTPRAVKA") == "checklist & cl & preotpravka"


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
    """Genuine follow-up ≤ SHORT_QUERY_EXPANSION_WORDS + history → expanded."""
    history = (
        HistoryTurn(role="user", content="Прочие поименованные лица"),
        HistoryTurn(
            role="assistant",
            content="Прочие поименованные лица включают: Тей Евгений Г., Омарова Г. М.",
        ),
    )
    result = _expand_query_with_history("а дальше?", history)
    assert result.startswith("а дальше? ")
    assert "Тей Евгений Г." in result


def test_original_query_unchanged_in_expansion() -> None:
    """The original query string is the prefix of the expansion."""
    original = "кто отвечает?"
    history = (
        HistoryTurn(role="assistant", content="Тей Евгений Г. — сотрудник."),
    )
    result = _expand_query_with_history(original, history)
    assert result.startswith(original)
    assert original == "кто отвечает?"


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
    result = _expand_query_with_history("а дальше?", history)
    assert len(result) <= SHORT_QUERY_EXPANSION_MAX_CHARS
    assert result.startswith("а дальше?")


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


# ===========================================================================
# Same-ACL users must get equivalent retrieval; expansion must not hijack FTS
# ===========================================================================

_PERSONNEL_BODY = (
    "Прочие поименованные лица\n\n"
    "Тей Евгений Г., Темир Ельнур Н., Гылымбек Алгыс,\n"
    "Джумадуллаева Н. И., Омарова Г. М., Рамиль\n\n"
    "Главный бухгалтер: Омарова Г. М."
)


async def test_unrelated_embedding_expansion_does_not_hide_lexical_name(
    article_service: ArticleService,
    retriever: KnowledgeRetriever,
    company_a: Company,
    employee_a: Employee,
) -> None:
    """Assistant history used for embeddings must not change FTS tokens.

    A short follow-up like "Евгений" after an unrelated answer used to be
    concatenated into to_tsquery, flipping AND→OR and drowning the name.
    """
    await _publish(
        article_service,
        company_a,
        title="общее сведение",
        body=_PERSONNEL_BODY,
    )
    unrelated = (
        "Евгений История Азерота древние эпохи возникновение основных конфликтов "
        "Артас Менетил Сильвана Ветрокрылая"
    )
    hits = await retriever.retrieve(
        "Евгений",
        actor_company_id=company_a.id,
        actor_employee_id=employee_a.id,
        embedding_query=unrelated,
        **_KWARGS,
    )
    assert hits, "Original-name FTS must still retrieve the personnel chunk"
    assert any("Евгений" in h.content for h in hits)


async def test_two_same_company_employees_same_hits_for_name_and_accountant(
    article_service: ArticleService,
    retriever: KnowledgeRetriever,
    company_a: Company,
    employee_a: Employee,
) -> None:
    """Two employees with the same company ACL must retrieve the same articles."""
    employee_peer = await _create_employee(
        company_id=company_a.id,
        role=EmployeeRole.EMPLOYEE.value,
    )
    await _publish(
        article_service,
        company_a,
        title="общее сведение",
        body=_PERSONNEL_BODY,
    )

    questions = ("Евгений", "Кто главный бухгалтер?")
    for question in questions:
        hits_a = await retriever.retrieve(
            question,
            actor_company_id=company_a.id,
            actor_employee_id=employee_a.id,
            **_KWARGS,
        )
        hits_b = await retriever.retrieve(
            question,
            actor_company_id=company_a.id,
            actor_employee_id=employee_peer.id,
            embedding_query=f"{question} unrelated prior assistant warcraft lore",
            **_KWARGS,
        )
        assert hits_a, f"employee A must retrieve KB for {question!r}"
        assert hits_b, f"employee B must retrieve KB for {question!r}"
        articles_a = {h.article_id for h in hits_a}
        articles_b = {h.article_id for h in hits_b}
        assert articles_a == articles_b, (
            f"same-ACL employees must retrieve the same articles for {question!r}"
        )


async def test_other_company_employee_cannot_retrieve_personnel_kb(
    article_service: ArticleService,
    retriever: KnowledgeRetriever,
    company_a: Company,
    company_b: Company,
    employee_a: Employee,
    employee_b: Employee,
) -> None:
    """Unauthorized tenant must not receive the other company's personnel KB."""
    await _publish(
        article_service,
        company_a,
        title="общее сведение",
        body=_PERSONNEL_BODY,
    )
    hits_b = await retriever.retrieve(
        "Евгений",
        actor_company_id=company_b.id,
        actor_employee_id=employee_b.id,
        **_KWARGS,
    )
    assert all("Евгений" not in h.content for h in hits_b)
    hits_a = await retriever.retrieve(
        "Евгений",
        actor_company_id=company_a.id,
        actor_employee_id=employee_a.id,
        **_KWARGS,
    )
    assert any("Евгений" in h.content for h in hits_a)


def _mock_chunk(
    *,
    article_id,
    content: str,
    chunk_index: int = 0,
    chunk_id=None,
):
    from app.db.models.knowledge_article_chunk import KnowledgeArticleChunk

    chunk = MagicMock(spec=KnowledgeArticleChunk)
    chunk.id = chunk_id or uuid4()
    chunk.article_id = article_id
    chunk.version_id = uuid4()
    chunk.chunk_index = chunk_index
    chunk.content = content
    return chunk


def test_standalone_topic_queries_are_not_expanded() -> None:
    """Production failures: topic nouns must not absorb the previous answer."""
    history = (
        HistoryTurn(role="assistant", content="Омарова Г. М. — специалист по сертификации [S1]."),
    )
    for query in ("AI-ассистент", "CRM", "Стоп-фактор", "CHECKLISTS", "Евгений"):
        assert _expand_query_with_history(query, history) == query
        assert "Омарова" not in _expand_query_with_history(query, history)


def test_skvoznoy_and_p13_and_checklist_code_not_expanded() -> None:
    """Successful production queries stay unexpanded (not follow-ups / too long)."""
    history = (
        HistoryTurn(role="assistant", content="Previous long answer about personnel."),
    )
    assert _expand_query_with_history("Сквозной порядок", history) == "Сквозной порядок"
    assert _expand_query_with_history("P13 Доставка по РК", history) == "P13 Доставка по РК"
    assert (
        _expand_query_with_history("CHECKLIST CL-PREOTPRAVKA", history)
        == "CHECKLIST CL-PREOTPRAVKA"
    )


def test_follow_up_queries_still_expand() -> None:
    """Short anaphoric follow-ups still use the last assistant for embeddings."""
    history = (
        HistoryTurn(role="assistant", content="Сквозной порядок: P01 затем P02."),
    )
    for query in ("а дальше?", "а кто?", "кто отвечает?"):
        result = _expand_query_with_history(query, history)
        assert result.startswith(query)
        assert "P01" in result


def test_no_answer_history_never_expands_embedding_query() -> None:
    """Exact NO_ANSWER assistant text must not distort embedding_query."""
    history = (
        HistoryTurn(role="assistant", content=NO_ANSWER_MESSAGE),
    )
    assert _expand_query_with_history("а дальше?", history) == "а дальше?"
    assert _expand_query_with_history("CRM", history) == "CRM"


def test_crm_definition_chunk_survives_per_article_cap() -> None:
    """Highest-ts_rank CRM definition is reserved even when neighbors score higher."""
    from app.services.ai.retriever import _merge_and_score

    article_id = uuid4()
    definition = _mock_chunk(
        article_id=article_id,
        chunk_index=29,
        content="CRM 4logist aliases: текущая CRM. Действующая CRM: сделки, грузы.",
    )
    neighbor_a = _mock_chunk(
        article_id=article_id,
        chunk_index=56,
        content="Груз должен быть заведён в CRM до момента забора.",
    )
    neighbor_b = _mock_chunk(
        article_id=article_id,
        chunk_index=57,
        content="domains: CRM, TRANSPORT_LOGISTICS tags: CRM",
    )
    hits = _merge_and_score(
        vector_rows=[
            (neighbor_a, 0.44, "общее сведение"),  # sim 0.56
            (neighbor_b, 0.47, "общее сведение"),  # sim 0.53
            (definition, 0.65, "общее сведение"),  # sim 0.35
        ],
        lexical_rows=[
            (definition, 0.41, "общее сведение"),
            (neighbor_a, 0.37, "общее сведение"),
            (neighbor_b, 0.20, "общее сведение"),
        ],
        top_k=5,
        min_score=None,
    )
    assert len(hits) <= MAX_CHUNKS_PER_ARTICLE_RESULT
    assert any(h.chunk_id == definition.id for h in hits), (
        "CRM definition chunk 29 must survive the per-article cap"
    )
    assert any("4logist" in h.content for h in hits)


def test_ai_assistant_lexical_chunk_survives_unrelated_vector_neighbors() -> None:
    """FTS AI-ассистент chunk is reserved when vector is dominated by another topic."""
    from app.services.ai.retriever import _merge_and_score

    article_id = uuid4()
    other_article = uuid4()
    ai_chunk = _mock_chunk(
        article_id=article_id,
        chunk_index=65,
        content="AI-ассистент всегда указывает источник и дату актуальности.",
    )
    unrelated_same = _mock_chunk(
        article_id=article_id,
        chunk_index=103,
        content="Сертификация и таможенное оформление без упоминания ассистента.",
    )
    other_topic = _mock_chunk(
        article_id=other_article,
        chunk_index=0,
        content="Омарова Г. М. — специалист по сертификации.",
    )
    hits = _merge_and_score(
        vector_rows=[
            (other_topic, 0.46, "ответственные лица"),  # sim 0.54
            (unrelated_same, 0.50, "общее сведение"),  # sim 0.50
        ],
        lexical_rows=[(ai_chunk, 0.09, "общее сведение")],
        top_k=5,
        min_score=None,
    )
    assert any(h.chunk_id == ai_chunk.id for h in hits)
    assert any("AI-ассистент" in h.content for h in hits)


def test_stop_factor_lexical_only_survives_same_article_vector_cap() -> None:
    """Lexical-only стоп-факторы chunk is reserved ahead of higher-cosine neighbors."""
    from app.services.ai.retriever import _merge_and_score

    article_id = uuid4()
    stop_chunk = _mock_chunk(
        article_id=article_id,
        chunk_index=77,
        content="Квалификация входящего запроса (стоп-факторы). Не принимаются: алкоголь.",
    )
    pipeline_a = _mock_chunk(
        article_id=article_id,
        chunk_index=66,
        content="Сквозной порядок P01 P02 P03 без стоп слова в этом окне.",
    )
    pipeline_b = _mock_chunk(
        article_id=article_id,
        chunk_index=97,
        content="Сбор расчётов формирование КП и сделки в CRM.",
    )
    hits = _merge_and_score(
        vector_rows=[
            (pipeline_a, 0.33, "общее сведение"),  # sim 0.67
            (pipeline_b, 0.37, "общее сведение"),  # sim 0.63
        ],
        lexical_rows=[(stop_chunk, 0.12, "общее сведение")],
        top_k=5,
        min_score=None,
    )
    assert any(h.chunk_id == stop_chunk.id for h in hits)
    assert any("стоп-факторы" in h.content for h in hits)
    assert len([h for h in hits if h.article_id == article_id]) <= MAX_CHUNKS_PER_ARTICLE_RESULT


def test_vector_only_ranking_unchanged_without_lexical_hits() -> None:
    """No FTS matches → per-article cap still keeps the highest cosine chunks."""
    from app.services.ai.retriever import _merge_and_score

    article_id = uuid4()
    high = _mock_chunk(article_id=article_id, chunk_index=1, content="best")
    mid = _mock_chunk(article_id=article_id, chunk_index=2, content="mid")
    low = _mock_chunk(article_id=article_id, chunk_index=3, content="low")
    hits = _merge_and_score(
        vector_rows=[
            (high, 0.10, "t"),
            (mid, 0.20, "t"),
            (low, 0.80, "t"),
        ],
        lexical_rows=[],
        top_k=5,
        min_score=None,
    )
    assert [h.chunk_id for h in hits] == [high.id, mid.id]


def test_checklists_lexical_hit_remains_in_final_retrieval() -> None:
    from app.services.ai.retriever import _merge_and_score

    article_id = uuid4()
    checklists = _mock_chunk(
        article_id=article_id,
        chunk_index=75,
        content="CHECKLISTS\nCHECKLIST CL-PREOTPRAVKA\nОбязательные сверки перед отправкой.",
    )
    p13_neighbor = _mock_chunk(
        article_id=article_id,
        chunk_index=92,
        content="Доставка по Казахстану (P13) ежедневно.",
    )
    hits = _merge_and_score(
        vector_rows=[
            (p13_neighbor, 0.27, "общее сведение"),
            (checklists, 0.33, "общее сведение"),
        ],
        lexical_rows=[(checklists, 0.09, "общее сведение")],
        top_k=5,
        min_score=None,
    )
    assert any(h.chunk_id == checklists.id for h in hits)
    assert any("CHECKLISTS" in h.content for h in hits)


async def test_hyphenated_stop_factor_fts_matches_plural(
    article_service: ArticleService,
    company_a: Company,
) -> None:
    """Postgres simple FTS: Стоп-фактор query hits indexed стоп-факторы."""
    article = await _publish(
        article_service,
        company_a,
        title="общее сведение",
        body="Не принимаются стоп-факторы по грузам: алкоголь, табак, скоропорт.",
    )
    tsquery = _build_tsquery("Стоп-фактор")
    assert tsquery is not None
    async with _uow_factory() as uow:
        await uow.enter_tenant(company_a.id)
        rows = await uow.knowledge_article_chunks.search_lexical_current_published(
            allowed_article_ids=[article.id],
            tsquery_text=tsquery,
            limit=10,
        )
    assert rows, "Prefix tsquery must match plural стоп-факторы"
    assert any("стоп-фактор" in row[0].content.lower() for row in rows)


async def test_production_queries_retrieve_matching_chunks(
    article_service: ArticleService,
    retriever: KnowledgeRetriever,
    company_a: Company,
    employee_a: Employee,
) -> None:
    """Live Telegram queries find the KB passages they failed or succeeded on."""
    body = (
        "Назначение корпуса: система для AI-ассистента, RAG и операционного поиска.\n\n"
        "ENTITY CRM 4logist. aliases: 4logist; текущая CRM. "
        "description: Действующая CRM: сделки, грузы, рейсы, документы, статусы.\n\n"
        "MODULE M-COMMON-STOP — стоп-факторы по грузам. Не принимаются: алкоголь.\n\n"
        "Сквозной порядок (основной поток сделки): P01 Квалификация запроса "
        "→ P02 Сбор данных о грузе → P03 Расчёт ставки.\n\n"
        "P13 Доставка по РК. Владелец: менеджер и логист по РК. Частота: ежедневно.\n\n"
        "CHECKLISTS\nCHECKLIST CL-PREOTPRAVKA\n"
        "title: Обязательные сверки перед отправкой груза. role: Логист ТЛО."
    )
    await _publish(article_service, company_a, title="общее сведение", body=body)
    kwargs = dict(
        actor_company_id=company_a.id,
        actor_employee_id=employee_a.id,
        **_KWARGS,
    )
    cases = (
        ("AI-ассистент", "AI-ассистент"),
        ("CRM", "CRM"),
        ("Стоп-фактор", "стоп-фактор"),
        ("CHECKLISTS", "CHECKLISTS"),
        ("Сквозной порядок", "Сквозной порядок"),
        ("P13 Доставка по РК", "P13"),
        ("CHECKLIST CL-PREOTPRAVKA", "CL-PREOTPRAVKA"),
    )
    unrelated = (
        "Омарова Г. М. специалист по сертификации Warcraft lore ancient kingdoms"
    )
    for query, needle in cases:
        hits = await retriever.retrieve(query, embedding_query=unrelated, **kwargs)
        assert hits, f"{query!r} must return hybrid hits"
        assert any(needle.lower() in h.content.lower() for h in hits), (
            f"{query!r} must keep a chunk containing {needle!r}"
        )


async def test_unrelated_embedding_does_not_drop_ai_assistant_lexical(
    article_service: ArticleService,
    retriever: KnowledgeRetriever,
    company_a: Company,
    employee_a: Employee,
) -> None:
    """Previous-topic embedding_query must not hide FTS AI-ассистент chunks."""
    await _publish(
        article_service,
        company_a,
        title="общее сведение",
        body=(
            "Политика AI-ассистента: всегда указывает источник. "
            "AI-ассистент не отвечает при отсутствии данных."
        ),
    )
    hits = await retriever.retrieve(
        "AI-ассистент",
        actor_company_id=company_a.id,
        actor_employee_id=employee_a.id,
        embedding_query=(
            "AI-ассистент Омарова Г. М. — специалист по сертификации [S1]."
        ),
        **_KWARGS,
    )
    assert hits
    assert any("AI-ассистент" in h.content for h in hits)

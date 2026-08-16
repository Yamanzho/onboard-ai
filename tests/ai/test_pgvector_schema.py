"""pgvector extension, chunk table, dimension, constraints."""

from __future__ import annotations

from sqlalchemy import text

from app.core.ai_constants import KB_CHUNK_VECTOR_DIMENSION
from tests.conftest import _uow_factory


async def test_vector_extension_is_available() -> None:
    async with _uow_factory() as uow:
        await uow.enter_platform()
        row = (
            await uow.session.execute(
                text(
                    "SELECT extname, extversion FROM pg_extension WHERE extname = 'vector'"
                )
            )
        ).one()
    assert row[0] == "vector"
    assert row[1]


async def test_knowledge_article_chunks_table_exists() -> None:
    async with _uow_factory() as uow:
        await uow.enter_platform()
        rel = (
            await uow.session.execute(
                text("SELECT to_regclass('public.knowledge_article_chunks')")
            )
        ).scalar_one()
    assert rel == "knowledge_article_chunks"


async def test_embedding_column_matches_kb_chunk_vector_dimension() -> None:
    async with _uow_factory() as uow:
        await uow.enter_platform()
        formatted = (
            await uow.session.execute(
                text(
                    """
                    SELECT format_type(a.atttypid, a.atttypmod)
                    FROM pg_attribute a
                    JOIN pg_class c ON c.oid = a.attrelid
                    JOIN pg_namespace n ON n.oid = c.relnamespace
                    WHERE n.nspname = 'public'
                      AND c.relname = 'knowledge_article_chunks'
                      AND a.attname = 'embedding'
                      AND a.attnum > 0
                      AND NOT a.attisdropped
                    """
                )
            )
        ).scalar_one()
    assert formatted == f"vector({KB_CHUNK_VECTOR_DIMENSION})"


async def test_unique_and_check_constraints_exist() -> None:
    async with _uow_factory() as uow:
        await uow.enter_platform()
        names = {
            row[0]
            for row in (
                await uow.session.execute(
                    text(
                        """
                        SELECT conname FROM pg_constraint
                        WHERE conrelid = 'public.knowledge_article_chunks'::regclass
                        """
                    )
                )
            ).all()
        }
    assert "uq_knowledge_article_chunks_version_id_chunk_index" in names
    assert "ck_knowledge_article_chunks_chunk_index_non_negative" in names
    assert "ck_knowledge_article_chunks_content_not_blank" in names


async def test_chunk_indexes_exist() -> None:
    async with _uow_factory() as uow:
        await uow.enter_platform()
        indexes = {
            row[0]
            for row in (
                await uow.session.execute(
                    text(
                        """
                        SELECT indexname FROM pg_indexes
                        WHERE schemaname = 'public'
                          AND tablename = 'knowledge_article_chunks'
                        """
                    )
                )
            ).all()
        }
    assert "ix_knowledge_article_chunks_company_id" in indexes
    assert "ix_knowledge_article_chunks_company_id_article_id" in indexes
    assert "ix_knowledge_article_chunks_company_id_version_id" in indexes
    assert "uq_knowledge_article_chunks_version_id_chunk_index" in indexes


async def test_no_ann_index_on_embedding() -> None:
    """Exact search for dim=8; HNSW/IVFFlat would be premature."""
    async with _uow_factory() as uow:
        await uow.enter_platform()
        ams = {
            row[0]
            for row in (
                await uow.session.execute(
                    text(
                        """
                        SELECT am.amname
                        FROM pg_index i
                        JOIN pg_class ic ON ic.oid = i.indexrelid
                        JOIN pg_am am ON am.oid = ic.relam
                        JOIN pg_class tc ON tc.oid = i.indrelid
                        WHERE tc.relname = 'knowledge_article_chunks'
                        """
                    )
                )
            ).all()
        }
    assert "hnsw" not in ams
    assert "ivfflat" not in ams


async def test_rls_is_enabled_and_forced() -> None:
    async with _uow_factory() as uow:
        await uow.enter_platform()
        row = (
            await uow.session.execute(
                text(
                    """
                    SELECT relrowsecurity, relforcerowsecurity
                    FROM pg_class
                    WHERE relname = 'knowledge_article_chunks'
                    """
                )
            )
        ).one()
    assert row[0] is True
    assert row[1] is True

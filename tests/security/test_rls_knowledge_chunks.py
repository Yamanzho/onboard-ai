"""Adversarial RLS for knowledge_article_chunks (onboard_app, real Postgres)."""

from __future__ import annotations

from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.ai_constants import KB_CHUNK_VECTOR_DIMENSION
from app.core.config import get_settings
from app.db.models.company import Company
from app.services.knowledge.article_service import ArticleService
from tests.security.test_rls_adversarial import _set_platform, _set_tenant


@pytest.fixture
async def app_role_session() -> AsyncSession:
    """Session connected as onboard_app (no BYPASSRLS)."""
    settings = get_settings()
    url = settings.database_url
    if "onboard_app" not in url and "onboard_owner" in url:
        url = url.replace("onboard_owner", "onboard_app")
    engine = create_async_engine(url, echo=False, connect_args={"ssl": False})
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        yield session
    await engine.dispose()

_VECTOR_LITERAL = "[" + ",".join("0.1" for _ in range(KB_CHUNK_VECTOR_DIMENSION)) + "]"


async def _insert_chunk(
    session: AsyncSession,
    *,
    company_id,
    article_id,
    version_id,
    content: str,
    chunk_index: int = 99,
) -> object:
    chunk_id = uuid4()
    await session.execute(
        text(
            """
            INSERT INTO knowledge_article_chunks
            (id, company_id, article_id, version_id, chunk_index, content,
             embedding, metadata, created_at, updated_at)
            VALUES
            (:id, :cid, :aid, :vid, :chunk_index, :content,
             CAST(:embedding AS vector), '{}'::jsonb, now(), now())
            """
        ),
        {
            "id": chunk_id,
            "cid": company_id,
            "aid": article_id,
            "vid": version_id,
            "chunk_index": chunk_index,
            "content": content,
            "embedding": _VECTOR_LITERAL,
        },
    )
    await session.commit()
    return chunk_id


async def _publish_article(article_service: ArticleService, company: Company, title: str):
    article = await article_service.create_article(
        company_id=company.id,
        actor_company_id=company.id,
        title=title,
        body=f"{title} body",
    )
    return await article_service.publish_article(article.id, company_id=company.id)


@pytest.mark.asyncio
async def test_chunks_force_rls_enabled(app_role_session: AsyncSession) -> None:
    row = (
        await app_role_session.execute(
            text(
                "SELECT relrowsecurity, relforcerowsecurity FROM pg_class "
                "WHERE relname = 'knowledge_article_chunks'"
            )
        )
    ).one()
    assert row[0] is True
    assert row[1] is True


@pytest.mark.asyncio
async def test_onboard_app_is_granted_dml_on_chunks(
    app_role_session: AsyncSession,
) -> None:
    has_insert = (
        await app_role_session.execute(
            text(
                """
                SELECT has_table_privilege('onboard_app',
                    'knowledge_article_chunks', 'INSERT')
                AND has_table_privilege('onboard_app',
                    'knowledge_article_chunks', 'SELECT')
                AND has_table_privilege('onboard_app',
                    'knowledge_article_chunks', 'DELETE')
                """
            )
        )
    ).scalar_one()
    assert has_insert is True


@pytest.mark.asyncio
async def test_tenant_a_cannot_select_tenant_b_chunks_even_with_uuid(
    company_a: Company,
    company_b: Company,
    article_service: ArticleService,
    app_role_session: AsyncSession,
) -> None:
    article_a = await _publish_article(article_service, company_a, "Article A")
    article_b = await _publish_article(article_service, company_b, "Article B")
    assert article_a.current_version_id is not None
    assert article_b.current_version_id is not None

    await _set_tenant(app_role_session, company_a.id)
    id_a = await _insert_chunk(
        app_role_session,
        company_id=company_a.id,
        article_id=article_a.id,
        version_id=article_a.current_version_id,
        content="chunk A secret",
    )
    await _set_tenant(app_role_session, company_b.id)
    id_b = await _insert_chunk(
        app_role_session,
        company_id=company_b.id,
        article_id=article_b.id,
        version_id=article_b.current_version_id,
        content="chunk B secret",
    )

    await _set_tenant(app_role_session, company_a.id)
    probed_b = (
        await app_role_session.execute(
            text("SELECT content FROM knowledge_article_chunks WHERE id = :id"),
            {"id": id_b},
        )
    ).first()
    assert probed_b is None
    own_a = (
        await app_role_session.execute(
            text("SELECT content FROM knowledge_article_chunks WHERE id = :id"),
            {"id": id_a},
        )
    ).first()
    assert own_a is not None
    assert own_a[0] == "chunk A secret"

    await _set_tenant(app_role_session, company_b.id)
    probed_a = (
        await app_role_session.execute(
            text("SELECT content FROM knowledge_article_chunks WHERE id = :id"),
            {"id": id_a},
        )
    ).first()
    assert probed_a is None
    own_b = (
        await app_role_session.execute(
            text("SELECT content FROM knowledge_article_chunks WHERE id = :id"),
            {"id": id_b},
        )
    ).first()
    assert own_b is not None
    assert own_b[0] == "chunk B secret"


@pytest.mark.asyncio
async def test_tenant_a_cannot_insert_chunk_for_company_b(
    company_a: Company,
    company_b: Company,
    article_service: ArticleService,
    app_role_session: AsyncSession,
) -> None:
    article_b = await _publish_article(article_service, company_b, "B only")
    assert article_b.current_version_id is not None
    await _set_tenant(app_role_session, company_a.id)
    with pytest.raises(Exception):
        await _insert_chunk(
            app_role_session,
            company_id=company_b.id,
            article_id=article_b.id,
            version_id=article_b.current_version_id,
            content="cross-tenant write",
        )
    await app_role_session.rollback()


@pytest.mark.asyncio
async def test_tenant_a_cannot_update_or_delete_tenant_b_chunks(
    company_a: Company,
    company_b: Company,
    article_service: ArticleService,
    app_role_session: AsyncSession,
) -> None:
    article_b = await _publish_article(article_service, company_b, "B mutate")
    assert article_b.current_version_id is not None
    await _set_tenant(app_role_session, company_b.id)
    id_b = await _insert_chunk(
        app_role_session,
        company_id=company_b.id,
        article_id=article_b.id,
        version_id=article_b.current_version_id,
        content="chunk B must stay",
        chunk_index=42,
    )

    await _set_tenant(app_role_session, company_a.id)
    updated = await app_role_session.execute(
        text(
            "UPDATE knowledge_article_chunks SET content = 'hijacked' WHERE id = :id"
        ),
        {"id": id_b},
    )
    assert updated.rowcount == 0
    await app_role_session.commit()

    deleted = await app_role_session.execute(
        text("DELETE FROM knowledge_article_chunks WHERE id = :id"),
        {"id": id_b},
    )
    assert deleted.rowcount == 0
    await app_role_session.commit()

    await _set_tenant(app_role_session, company_b.id)
    remaining = (
        await app_role_session.execute(
            text("SELECT content FROM knowledge_article_chunks WHERE id = :id"),
            {"id": id_b},
        )
    ).first()
    assert remaining is not None
    assert remaining[0] == "chunk B must stay"


@pytest.mark.asyncio
async def test_platform_can_select_both_tenants_chunks(
    company_a: Company,
    company_b: Company,
    article_service: ArticleService,
    app_role_session: AsyncSession,
) -> None:
    article_a = await _publish_article(article_service, company_a, "A plat")
    article_b = await _publish_article(article_service, company_b, "B plat")
    await _set_tenant(app_role_session, company_a.id)
    await _insert_chunk(
        app_role_session,
        company_id=company_a.id,
        article_id=article_a.id,
        version_id=article_a.current_version_id,
        content="A plat chunk",
    )
    await _set_tenant(app_role_session, company_b.id)
    await _insert_chunk(
        app_role_session,
        company_id=company_b.id,
        article_id=article_b.id,
        version_id=article_b.current_version_id,
        content="B plat chunk",
    )

    await _set_platform(app_role_session)
    rows = (
        await app_role_session.execute(
            text(
                "SELECT content FROM knowledge_article_chunks "
                "WHERE content IN ('A plat chunk', 'B plat chunk') "
                "ORDER BY content"
            )
        )
    ).all()
    assert [r[0] for r in rows] == ["A plat chunk", "B plat chunk"]

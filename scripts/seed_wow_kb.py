#!/usr/bin/env python3
"""Idempotent World of Warcraft lore KB seed for the Demo Company tenant.

Creates or updates only the wow-test-corpus-v1 articles. Does not touch other
tenants or non-corpus knowledge articles.

Run (after migrations and demo seed):

    python -m scripts.seed_wow_kb
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
from pathlib import Path
from typing import Any
from uuid import UUID

from sqlalchemy import text

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from app.core.exceptions import ConflictError  # noqa: E402
from app.db.enums import (  # noqa: E402
    KnowledgeArticleStatus,
    KnowledgeBodyFormat,
    KnowledgeVisibility,
)
from app.db.models.company import Company  # noqa: E402
from app.db.session import async_session_factory  # noqa: E402
from app.db.uow import UnitOfWork  # noqa: E402
from app.services.knowledge.article_service import ArticleService  # noqa: E402
from app.services.knowledge.category_service import CategoryService  # noqa: E402
from app.services.knowledge.tag_service import TagService  # noqa: E402
from scripts.seed_demo import DEMO_ADMIN_ID, DEMO_COMPANY_ID  # noqa: E402

logger = logging.getLogger("seed_wow_kb")

CORPUS_PATH = _ROOT / "tests" / "fixtures" / "wow" / "corpus.json"
FORBIDDEN_SLUGS = frozenset({"aoe", "yamanzho"})
FORBIDDEN_NAME_FRAGMENTS = ("aoe", "yamanzho")
REQUIRED_SLUG = "demo"


class UnsafeTenantError(RuntimeError):
    """Raised when the seed is pointed at a non-demo / customer tenant."""


def assert_safe_demo_tenant(company: Company) -> None:
    """Refuse any tenant that is not the local Demo Company."""
    slug = (company.slug or "").strip().lower()
    name = (company.name or "").strip().lower()
    if company.id != DEMO_COMPANY_ID:
        raise UnsafeTenantError(
            f"Refusing to seed company {company.id}: WoW corpus is locked to "
            f"Demo Company ({DEMO_COMPANY_ID})"
        )
    if slug != REQUIRED_SLUG:
        raise UnsafeTenantError(
            f"Refusing to seed company slug {company.slug!r}: expected {REQUIRED_SLUG!r}"
        )
    if slug in FORBIDDEN_SLUGS or any(fragment in name for fragment in FORBIDDEN_NAME_FRAGMENTS):
        raise UnsafeTenantError(
            f"Refusing to seed tenant {company.name!r} ({company.slug}): "
            "customer companies are out of scope"
        )


def load_corpus() -> dict[str, Any]:
    return json.loads(CORPUS_PATH.read_text(encoding="utf-8"))


async def _ensure_category(
    category_service: CategoryService,
    *,
    company_id: UUID,
    name: str,
    slug: str,
) -> UUID:
    async with UnitOfWork(session_factory=async_session_factory) as uow:
        await uow.enter_tenant(company_id)
        existing = await uow.knowledge_categories.get_by_slug(company_id, slug)
        if existing is not None:
            return existing.id
    try:
        created = await category_service.create_category(
            company_id=company_id,
            actor_company_id=company_id,
            name=name,
            slug=slug,
        )
        return created.id
    except ConflictError:
        async with UnitOfWork(session_factory=async_session_factory) as uow:
            await uow.enter_tenant(company_id)
            existing = await uow.knowledge_categories.get_by_slug(company_id, slug)
            if existing is None:
                raise
            return existing.id


async def _ensure_tag(
    tag_service: TagService,
    *,
    company_id: UUID,
    name: str,
    slug: str,
) -> UUID:
    async with UnitOfWork(session_factory=async_session_factory) as uow:
        await uow.enter_tenant(company_id)
        existing = await uow.knowledge_tags.get_by_slug(company_id, slug)
        if existing is not None:
            return existing.id
    try:
        created = await tag_service.create_tag(
            company_id=company_id,
            actor_company_id=company_id,
            name=name,
            slug=slug,
        )
        return created.id
    except ConflictError:
        async with UnitOfWork(session_factory=async_session_factory) as uow:
            await uow.enter_tenant(company_id)
            existing = await uow.knowledge_tags.get_by_slug(company_id, slug)
            if existing is None:
                raise
            return existing.id


async def _find_article_by_identity_tag(
    article_service: ArticleService,
    *,
    company_id: UUID,
    identity_tag_id: UUID,
) -> Any | None:
    articles = await article_service.list_articles(
        company_id,
        actor_company_id=company_id,
        tag_id=identity_tag_id,
        offset=0,
        limit=10,
    )
    if not articles:
        return None
    return articles[0]


async def _created_by_id(company_id: UUID) -> UUID | None:
    async with UnitOfWork(session_factory=async_session_factory) as uow:
        await uow.enter_tenant(company_id)
        admin = await uow.employees.get_by_id(DEMO_ADMIN_ID)
        if admin is not None and admin.company_id == company_id:
            return admin.id
        return None


async def _index_report(company_id: UUID, article_ids: list[UUID]) -> dict[str, Any]:
    """Report on the existing indexing pipeline without changing it."""
    report: dict[str, Any] = {
        "pipeline": "absent",
        "chunks_count": None,
        "indexed_count": None,
        "detail": (
            "No app.services.ai indexer and no knowledge_article_chunks table "
            "in the current working tree; corpus was not re-embedded."
        ),
    }
    try:
        import importlib

        importlib.import_module("app.services.ai.indexer")
        report["pipeline"] = "present"
        report["detail"] = "Indexer module imported; no automatic reindex invoked."
    except ModuleNotFoundError:
        pass

    async with UnitOfWork(session_factory=async_session_factory) as uow:
        await uow.enter_tenant(company_id)
        exists = await uow.session.scalar(
            text("SELECT to_regclass('public.knowledge_article_chunks')")
        )
        if exists is None:
            return report

        chunk_count = await uow.session.scalar(
            text(
                "SELECT COUNT(*) FROM knowledge_article_chunks "
                "WHERE company_id = :company_id AND article_id = ANY(:ids)"
            ),
            {"company_id": company_id, "ids": article_ids},
        )
        report["chunks_count"] = int(chunk_count or 0)
        if report["pipeline"] == "absent":
            report["detail"] = (
                "Chunks table exists but indexer module is absent; "
                "no reindex was performed."
            )
    return report


async def seed() -> dict[str, Any]:
    corpus = load_corpus()
    article_service = ArticleService()
    category_service = CategoryService()
    tag_service = TagService()

    async with UnitOfWork(session_factory=async_session_factory) as uow:
        await uow.enter_platform()
        company = await uow.companies.get_by_id(DEMO_COMPANY_ID)

    if company is None:
        raise SystemExit(
            "Demo Company not found. Run `python -m scripts.seed_demo` first. "
            f"Expected company id {DEMO_COMPANY_ID}."
        )
    try:
        assert_safe_demo_tenant(company)
    except UnsafeTenantError as exc:
        raise SystemExit(str(exc)) from exc

    company_id = company.id
    actor_id = await _created_by_id(company_id)
    category_id = await _ensure_category(
        category_service,
        company_id=company_id,
        name=str(corpus["category"]["name"]),
        slug=str(corpus["category"]["slug"]),
    )
    corpus_tag_id = await _ensure_tag(
        tag_service,
        company_id=company_id,
        name=str(corpus["corpus_tag"]["name"]),
        slug=str(corpus["corpus_tag"]["slug"]),
    )

    results: list[dict[str, Any]] = []
    version_total = 0

    for spec in corpus["articles"]:
        identity_slug = str(spec["identity_tag"])
        identity_tag_id = await _ensure_tag(
            tag_service,
            company_id=company_id,
            name=identity_slug,
            slug=identity_slug,
        )
        tag_ids = [corpus_tag_id, identity_tag_id]
        for tag_slug in spec["tags"]:
            tag_ids.append(
                await _ensure_tag(
                    tag_service,
                    company_id=company_id,
                    name=str(tag_slug),
                    slug=str(tag_slug),
                )
            )
        # Preserve order, drop duplicates.
        tag_ids = list(dict.fromkeys(tag_ids))

        existing = await _find_article_by_identity_tag(
            article_service,
            company_id=company_id,
            identity_tag_id=identity_tag_id,
        )
        title = str(spec["title"])
        body = str(spec["body"])
        action = "created"

        if existing is None:
            article = await article_service.create_article(
                company_id=company_id,
                actor_company_id=company_id,
                title=title,
                body=body,
                body_format=KnowledgeBodyFormat.MARKDOWN.value,
                category_id=category_id,
                visibility=KnowledgeVisibility.COMPANY.value,
                tag_ids=tag_ids,
                change_summary=str(corpus["change_summary"]),
                created_by_id=actor_id,
            )
            article = await article_service.publish_article(
                article.id,
                company_id=company_id,
            )
            action = "created_published"
        else:
            article = existing
            if article.status == KnowledgeArticleStatus.ARCHIVED.value:
                action = "skipped_archived"
            else:
                current = article.current_version
                content_changed = current is None or current.title != title or current.body != body
                tags_changed = {tag.id for tag in (article.tags or [])} != set(tag_ids)
                category_changed = article.category_id != category_id
                updates: dict[str, Any] = {}
                if content_changed:
                    updates["title"] = title
                    updates["body"] = body
                    updates["body_format"] = KnowledgeBodyFormat.MARKDOWN.value
                    updates["change_summary"] = str(corpus["change_summary"])
                if tags_changed:
                    updates["tag_ids"] = tag_ids
                if category_changed:
                    updates["category_id"] = category_id
                if updates:
                    article = await article_service.update_article(
                        article.id,
                        company_id=company_id,
                        created_by_id=actor_id,
                        **updates,
                    )
                    action = "updated"
                else:
                    action = "unchanged"
                if article.status == KnowledgeArticleStatus.DRAFT.value:
                    article = await article_service.publish_article(
                        article.id,
                        company_id=company_id,
                    )
                    action = "updated_published"

        async with UnitOfWork(session_factory=async_session_factory) as uow:
            await uow.enter_tenant(company_id)
            versions = await uow.knowledge_article_versions.list_by_article_id(
                article.id,
                offset=0,
                limit=100,
            )
            version_total += len(versions)
            current_version = article.current_version.version if article.current_version else None

        row = {
            "corpus_id": spec["id"],
            "article_id": str(article.id),
            "title": title,
            "status": article.status,
            "current_version": current_version,
            "versions": len(versions),
            "action": action,
        }
        results.append(row)
        logger.info(
            "%s %s article_id=%s status=%s v%s",
            action,
            spec["id"],
            article.id,
            article.status,
            current_version,
        )

    article_ids = [UUID(row["article_id"]) for row in results]
    indexing = await _index_report(company_id, article_ids)

    summary = {
        "tenant": {"id": str(company_id), "slug": company.slug, "name": company.name},
        "corpus_id": corpus["corpus_id"],
        "articles": results,
        "article_count": len(results),
        "version_count": version_total,
        "indexing": indexing,
    }
    return summary


def _print_summary(summary: dict[str, Any]) -> None:
    print()
    print("=== WoW KB corpus seed ===")
    tenant = summary["tenant"]
    print(f"Tenant:          {tenant['name']} ({tenant['slug']}) {tenant['id']}")
    print(f"Corpus:          {summary['corpus_id']}")
    print(f"Articles:        {summary['article_count']}")
    print(f"Versions:        {summary['version_count']}")
    print("Articles:")
    for row in summary["articles"]:
        print(
            f"  - {row['corpus_id']}: {row['article_id']} "
            f"status={row['status']} v{row['current_version']} ({row['action']})"
        )
    indexing = summary["indexing"]
    print(f"Indexing:        {indexing['pipeline']}")
    print(f"Chunks:          {indexing['chunks_count']}")
    print(f"Index detail:    {indexing['detail']}")
    print()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    summary = asyncio.run(seed())
    _print_summary(summary)


if __name__ == "__main__":
    main()

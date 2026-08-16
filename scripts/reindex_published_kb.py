#!/usr/bin/env python3
"""Reindex current published KB chunks for one tenant.

Run after migrating the embedding column or switching embedding provider.
Does not change ArticleService ACL. Super Admin impersonation is not added.

    python -m scripts.reindex_published_kb --company-id <uuid>

``--company-id`` is the authenticated tenant. A mismatch with a second
claimed id is rejected the same way as the HTTP API.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path
from uuid import UUID

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from app.db.enums import EmployeeRole  # noqa: E402
from app.services.ai.indexer import KnowledgeChunkIndexer  # noqa: E402

logger = logging.getLogger("reindex_published_kb")


async def _run(*, company_id: UUID, claimed_company_id: UUID | None) -> None:
    indexer = KnowledgeChunkIndexer()
    result = await indexer.reindex_published_corpus(
        actor_company_id=company_id,
        actor_employee_id=company_id,
        actor_role=EmployeeRole.ADMIN.value,
        claimed_company_id=claimed_company_id,
    )
    logger.info(
        "reindex_done company_id=%s article_count=%s chunk_count=%s",
        company_id,
        result.indexed_articles,
        result.indexed_chunks,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--company-id",
        required=True,
        type=UUID,
        help="Authenticated tenant to reindex (JWT company equivalent)",
    )
    parser.add_argument(
        "--claimed-company-id",
        type=UUID,
        default=None,
        help="Optional claimed tenant; must match --company-id when set",
    )
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    asyncio.run(
        _run(company_id=args.company_id, claimed_company_id=args.claimed_company_id)
    )


if __name__ == "__main__":
    main()

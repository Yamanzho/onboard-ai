from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from prometheus_client import generate_latest

from app.core.metrics import REGISTRY, refresh_durable_metrics
from app.db.enums import KnowledgeIndexStatus
from app.db.models.knowledge_article import KnowledgeArticle
from app.db.models.knowledge_article_version import KnowledgeArticleVersion
from app.db.models.telegram_outbound_message import TelegramOutboundMessage
from app.db.uow import UnitOfWork


@pytest.mark.asyncio
async def test_durable_metrics_reflect_database_failure_state(
    company_a,
    employee_a,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    article_id = uuid4()
    version_id = uuid4()
    receipt_id = uuid4()
    now = datetime.now(UTC)
    async with UnitOfWork() as uow:
        await uow.enter_tenant(company_a.id)
        article = await uow.knowledge_articles.create(
            KnowledgeArticle(
                id=article_id,
                company_id=company_a.id,
                status="published",
                visibility="company",
                created_by_id=employee_a.id,
            )
        )
        await uow.session.flush()
        await uow.knowledge_article_versions.create(
            KnowledgeArticleVersion(
                id=version_id,
                company_id=company_a.id,
                article_id=article_id,
                version=1,
                title="Monitoring fixture",
                body="Safe fixture body",
                body_format="plain",
                published_at=now,
                index_status=KnowledgeIndexStatus.FAILED.value,
                indexing_failed_at=now,
                failure_category="provider_unavailable",
            )
        )
        article.current_version_id = version_id
        await uow.telegram_outbound.enqueue(
            TelegramOutboundMessage(
                id=uuid4(),
                company_id=company_a.id,
                employee_id=employee_a.id,
                chat_id=12345,
                source_type="quiz_result",
                source_key=f"monitoring:{uuid4()}",
                body="Safe outbound fixture",
                status="pending",
                attempt_count=0,
                next_attempt_at=now - timedelta(minutes=10),
            )
        )
        await uow.idempotency_receipts.claim(
            receipt_id=receipt_id,
            scope=f"employee:{employee_a.id}",
            operation="ai-chat",
            idempotency_key=f"monitoring:{uuid4()}",
            request_hash="0" * 64,
            owner_token=uuid4(),
            lease_expires_at=now - timedelta(minutes=5),
            company_id=company_a.id,
            employee_id=employee_a.id,
        )
        await uow.commit()

    async def _skip_redis() -> None:
        return None

    monkeypatch.setattr("app.core.metrics._refresh_redis_metrics", _skip_redis)
    await refresh_durable_metrics()
    payload = generate_latest(REGISTRY).decode()
    assert 'onboardai_telegram_outbound_messages{status="pending"}' in payload
    assert "onboardai_telegram_outbound_due 1.0" in payload
    assert 'onboardai_idempotency_stale_leases{operation="ai-chat"} 1.0' in payload
    assert 'onboardai_kb_current_versions{status="failed"} 1.0' in payload

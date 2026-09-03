from __future__ import annotations

from uuid import uuid4

import pytest
from prometheus_client import generate_latest

from app.core.metrics import (
    AI_PROVIDER_TOKENS,
    REGISTRY,
    record_provider_usage,
)


@pytest.mark.asyncio
async def test_metrics_endpoint_is_prometheus_and_uses_route_templates(
    api_client,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _no_refresh() -> None:
        return None

    monkeypatch.setattr("app.core.metrics.refresh_durable_metrics", _no_refresh)
    resource_id = str(uuid4())
    await api_client.get(f"/api/v1/knowledge/articles/{resource_id}")
    response = await api_client.get("/metrics")

    assert response.status_code == 200
    assert "text/plain" in response.headers["content-type"]
    assert "onboardai_http_requests_total" in response.text
    assert 'route="/knowledge/articles/{article_id}"' in response.text
    assert resource_id not in response.text


@pytest.mark.asyncio
async def test_metrics_output_has_no_sensitive_identity_labels(
    api_client,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def _no_refresh() -> None:
        return None

    monkeypatch.setattr("app.core.metrics.refresh_durable_metrics", _no_refresh)
    body = (await api_client.get("/metrics")).text.lower()
    for forbidden in (
        "employee_id=",
        "company_id=",
        "conversation_id=",
        "telegram_user_id=",
        "message_id=",
        "request_id=",
        "authorization",
        "jwt",
    ):
        assert forbidden not in body


def test_provider_usage_exports_bounded_token_types() -> None:
    record_provider_usage(
        model="gpt-test",
        operation="llm",
        usage={
            "prompt_tokens": 11,
            "completion_tokens": 7,
            "total_tokens": 18,
        },
    )
    payload = generate_latest(REGISTRY).decode()
    assert (
        'onboardai_ai_provider_tokens_total{model="gpt-test",operation="llm",'
        'provider="openai",token_type="input"}'
    ) in payload
    assert AI_PROVIDER_TOKENS is not None

"""TagService create/duplicate and tenancy checks."""

from __future__ import annotations

import pytest

from app.core.exceptions import ConflictError, NotFoundError
from app.db.models.company import Company
from app.services.knowledge.tag_service import TagService
from tests.conftest import auth_header


@pytest.mark.asyncio
async def test_create_tag(
    tag_service: TagService,
    company_a: Company,
) -> None:
    tag = await tag_service.create_tag(
        company_id=company_a.id,
        actor_company_id=company_a.id,
        name="Security",
        slug="security",
    )
    assert tag.name == "Security"
    assert tag.slug == "security"
    assert tag.company_id == company_a.id


@pytest.mark.asyncio
async def test_create_tag_derives_slug_from_name(
    tag_service: TagService,
    company_a: Company,
) -> None:
    tag = await tag_service.create_tag(
        company_id=company_a.id,
        actor_company_id=company_a.id,
        name="On Call Tips",
    )
    assert tag.slug == "on-call-tips"


@pytest.mark.asyncio
async def test_duplicate_tag(
    tag_service: TagService,
    company_a: Company,
) -> None:
    await tag_service.create_tag(
        company_id=company_a.id,
        actor_company_id=company_a.id,
        name="First",
        slug="dup-tag",
    )
    with pytest.raises(ConflictError, match="already exists"):
        await tag_service.create_tag(
            company_id=company_a.id,
            actor_company_id=company_a.id,
            name="Second",
            slug="dup-tag",
        )


@pytest.mark.asyncio
async def test_same_slug_allowed_in_different_companies(
    tag_service: TagService,
    company_a: Company,
    company_b: Company,
) -> None:
    tag_a = await tag_service.create_tag(
        company_id=company_a.id,
        actor_company_id=company_a.id,
        name="Shared name",
        slug="shared-slug",
    )
    tag_b = await tag_service.create_tag(
        company_id=company_b.id,
        actor_company_id=company_b.id,
        name="Shared name",
        slug="shared-slug",
    )
    assert tag_a.id != tag_b.id
    assert tag_a.company_id == company_a.id
    assert tag_b.company_id == company_b.id


@pytest.mark.asyncio
async def test_cannot_get_tag_from_other_company(
    tag_service: TagService,
    company_a: Company,
    company_b: Company,
) -> None:
    tag = await tag_service.create_tag(
        company_id=company_a.id,
        actor_company_id=company_a.id,
        name="Local",
        slug="local-tag",
    )
    with pytest.raises(NotFoundError, match="not found"):
        await tag_service.get_tag(tag.id, company_id=company_b.id)


@pytest.mark.asyncio
async def test_api_duplicate_tag_returns_409(
    api_client,
    tag_service: TagService,
    company_a: Company,
    hr_a,
) -> None:
    await tag_service.create_tag(
        company_id=company_a.id,
        actor_company_id=company_a.id,
        name="Existing",
        slug="dup-api-tag",
    )
    response = await api_client.post(
        "/api/v1/knowledge/tags",
        headers=auth_header(hr_a),
        json={
            "company_id": str(company_a.id),
            "name": "Again",
            "slug": "dup-api-tag",
        },
    )
    assert response.status_code == 409
    assert "already exists" in response.json()["detail"].lower()

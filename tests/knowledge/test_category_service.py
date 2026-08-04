"""CategoryService create/hierarchy/duplicate and tenancy checks."""

from __future__ import annotations

import pytest

from app.core.exceptions import ConflictError, NotFoundError
from app.db.models.company import Company
from app.services.knowledge.category_service import CategoryService
from tests.conftest import auth_header


@pytest.mark.asyncio
async def test_create_category(
    category_service: CategoryService,
    company_a: Company,
) -> None:
    category = await category_service.create_category(
        company_id=company_a.id,
        actor_company_id=company_a.id,
        name="Company Policies",
        slug="company-policies",
        position=1,
    )
    assert category.name == "Company Policies"
    assert category.slug == "company-policies"
    assert category.company_id == company_a.id
    assert category.parent_id is None
    assert category.position == 1


@pytest.mark.asyncio
async def test_duplicate_slug_error(
    category_service: CategoryService,
    company_a: Company,
) -> None:
    await category_service.create_category(
        company_id=company_a.id,
        actor_company_id=company_a.id,
        name="First",
        slug="same-slug",
    )
    with pytest.raises(ConflictError, match="already exists"):
        await category_service.create_category(
            company_id=company_a.id,
            actor_company_id=company_a.id,
            name="Second",
            slug="same-slug",
        )


@pytest.mark.asyncio
async def test_parent_category(
    category_service: CategoryService,
    company_a: Company,
) -> None:
    parent = await category_service.create_category(
        company_id=company_a.id,
        actor_company_id=company_a.id,
        name="Root",
        slug="root",
    )
    child = await category_service.create_category(
        company_id=company_a.id,
        actor_company_id=company_a.id,
        name="Child",
        slug="child",
        parent_id=parent.id,
    )
    assert child.parent_id == parent.id

    children = await category_service.list_categories(
        company_a.id,
        actor_company_id=company_a.id,
        parent_id=parent.id,
    )
    assert [c.id for c in children] == [child.id]


@pytest.mark.asyncio
async def test_cannot_use_parent_from_other_company(
    category_service: CategoryService,
    company_a: Company,
    company_b: Company,
) -> None:
    foreign_parent = await category_service.create_category(
        company_id=company_b.id,
        actor_company_id=company_b.id,
        name="Other root",
        slug="other-root",
    )
    with pytest.raises(NotFoundError, match="category"):
        await category_service.create_category(
            company_id=company_a.id,
            actor_company_id=company_a.id,
            name="Hijack",
            slug="hijack",
            parent_id=foreign_parent.id,
        )


@pytest.mark.asyncio
async def test_cannot_get_category_from_other_company(
    category_service: CategoryService,
    company_a: Company,
    company_b: Company,
) -> None:
    category = await category_service.create_category(
        company_id=company_a.id,
        actor_company_id=company_a.id,
        name="Local",
        slug="local",
    )
    with pytest.raises(NotFoundError, match="not found"):
        await category_service.get_category(category.id, company_id=company_b.id)


@pytest.mark.asyncio
async def test_api_duplicate_category_slug_returns_409(
    api_client,
    category_service: CategoryService,
    company_a: Company,
    hr_a,
) -> None:
    await category_service.create_category(
        company_id=company_a.id,
        actor_company_id=company_a.id,
        name="Existing",
        slug="dup-cat",
    )
    response = await api_client.post(
        "/api/v1/knowledge/categories",
        headers=auth_header(hr_a),
        json={
            "company_id": str(company_a.id),
            "name": "Again",
            "slug": "dup-cat",
        },
    )
    assert response.status_code == 409
    assert "already exists" in response.json()["detail"].lower()


@pytest.mark.asyncio
async def test_api_cannot_update_category_of_other_company(
    api_client,
    category_service: CategoryService,
    company_a: Company,
    hr_b,
) -> None:
    category = await category_service.create_category(
        company_id=company_a.id,
        actor_company_id=company_a.id,
        name="Locked",
        slug="locked",
    )
    response = await api_client.patch(
        f"/api/v1/knowledge/categories/{category.id}",
        headers=auth_header(hr_b),
        json={"name": "Hacked"},
    )
    assert response.status_code == 404

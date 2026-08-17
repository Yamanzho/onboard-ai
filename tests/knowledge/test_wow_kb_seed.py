"""WoW corpus seed stays on Demo Company; KB ACL is not weakened."""

from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest
from httpx import AsyncClient

from app.db.enums import KnowledgeArticleStatus, KnowledgeVisibility
from app.db.models.company import Company
from app.db.models.employee import Employee
from app.services.knowledge.article_service import ArticleService
from app.services.knowledge.tag_service import TagService
from scripts.seed_demo import DEMO_COMPANY_ID
from scripts.seed_wow_kb import UnsafeTenantError, assert_safe_demo_tenant
from tests.conftest import auth_header


def test_assert_safe_demo_tenant_accepts_demo_company() -> None:
    company = SimpleNamespace(
        id=DEMO_COMPANY_ID,
        slug="demo",
        name="Demo Company",
    )
    assert_safe_demo_tenant(company)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("company_id", "slug", "name"),
    [
        (uuid4(), "demo", "Demo Company"),
        (DEMO_COMPANY_ID, "aoe", "aoe"),
        (DEMO_COMPANY_ID, "yamanzho", "Yamanzho"),
        (DEMO_COMPANY_ID, "customer", "Customer Co"),
    ],
)
def test_assert_safe_demo_tenant_rejects_customer_tenants(
    company_id,
    slug: str,
    name: str,
) -> None:
    company = SimpleNamespace(id=company_id, slug=slug, name=name)
    with pytest.raises(UnsafeTenantError):
        assert_safe_demo_tenant(company)  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_wow_tagged_article_is_invisible_to_other_company(
    api_client: AsyncClient,
    article_service: ArticleService,
    tag_service: TagService,
    company_a: Company,
    company_b: Company,
    employee_a: Employee,
    hr_a: Employee,
    hr_b: Employee,
) -> None:
    """Reuse existing KB ACL: Demo-style WoW articles stay tenant-scoped."""
    tag = await tag_service.create_tag(
        company_id=company_a.id,
        actor_company_id=company_a.id,
        name="wow-test-corpus-v1",
        slug="wow-test-corpus-v1",
    )
    article = await article_service.create_article(
        company_id=company_a.id,
        actor_company_id=company_a.id,
        title="Артас Менетил: от принца Лордерона до Короля-лича",
        body="Ледяная Скорбь — уникальный маркер корпуса.",
        visibility=KnowledgeVisibility.COMPANY.value,
        tag_ids=[tag.id],
        created_by_id=hr_a.id,
    )
    published = await article_service.publish_article(
        article.id,
        company_id=company_a.id,
    )
    assert published.status == KnowledgeArticleStatus.PUBLISHED.value

    own = await api_client.get(
        f"/api/v1/knowledge/articles/{article.id}",
        headers=auth_header(employee_a),
    )
    assert own.status_code == 200, own.text
    assert "Ледяная Скорбь" in own.text

    foreign = await api_client.get(
        f"/api/v1/knowledge/articles/{article.id}",
        headers=auth_header(hr_b),
    )
    assert foreign.status_code == 404, foreign.text
    assert "Ледяная Скорбь" not in foreign.text

    listed = await api_client.get(
        "/api/v1/knowledge/articles",
        params={"company_id": str(company_b.id)},
        headers=auth_header(hr_b),
    )
    assert listed.status_code == 200, listed.text
    ids = {item["id"] for item in listed.json()["items"]}
    assert str(article.id) not in ids

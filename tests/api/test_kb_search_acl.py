"""KB search must respect tenant isolation, RBAC, and visibility ACL."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from httpx import AsyncClient

from app.db.enums import AssignmentStatus, KnowledgeVisibility
from app.db.models.assignment import Assignment
from app.db.models.company import Company
from app.db.models.employee import Employee
from app.db.models.onboarding_program import OnboardingProgram
from app.services.knowledge.article_service import ArticleService
from tests.conftest import _uow_factory, auth_header


def _list_url(company_id, q: str, status: str | None = None) -> str:
    params = f"company_id={company_id}&q={q}"
    if status:
        params += f"&status={status}"
    return f"/api/v1/knowledge/articles?{params}"


async def _create_program(company_id) -> OnboardingProgram:
    async with _uow_factory() as uow:
        await uow.enter_platform()
        program = await uow.onboarding_programs.create(
            OnboardingProgram(
                company_id=company_id,
                title=f"Program {uuid4().hex[:8]}",
                is_active=True,
            ),
        )
        await uow.commit()
        return program


async def _assign_employee(*, company_id, employee_id, program_id) -> Assignment:
    async with _uow_factory() as uow:
        await uow.enter_platform()
        assignment = await uow.assignments.create(
            Assignment(
                company_id=company_id,
                employee_id=employee_id,
                program_id=program_id,
                status=AssignmentStatus.IN_PROGRESS.value,
                assigned_at=datetime.now(UTC),
            ),
        )
        await uow.commit()
        return assignment


@pytest.mark.asyncio
async def test_search_matches_title_and_body(
    api_client: AsyncClient,
    article_service: ArticleService,
    company_a: Company,
    hr_a: Employee,
) -> None:
    token = uuid4().hex[:10]
    title_article = await article_service.create_article(
        company_id=company_a.id,
        actor_company_id=company_a.id,
        title=f"Title {token} handbook",
        body="unrelated body",
    )
    body_article = await article_service.create_article(
        company_id=company_a.id,
        actor_company_id=company_a.id,
        title="Other article",
        body=f"VPN setup uses {token} client",
    )
    await article_service.publish_article(title_article.id, company_id=company_a.id)
    await article_service.publish_article(body_article.id, company_id=company_a.id)

    response = await api_client.get(
        _list_url(company_a.id, token),
        headers=auth_header(hr_a),
    )
    assert response.status_code == 200, response.text
    titles = {item["current_version"]["title"] for item in response.json()["items"]}
    assert f"Title {token} handbook" in titles
    assert "Other article" in titles


@pytest.mark.asyncio
async def test_employee_search_hides_unpublished_and_other_tenant(
    api_client: AsyncClient,
    article_service: ArticleService,
    company_a: Company,
    company_b: Company,
    employee_a: Employee,
    hr_b: Employee,
) -> None:
    secret = uuid4().hex[:10]
    draft = await article_service.create_article(
        company_id=company_a.id,
        actor_company_id=company_a.id,
        title=f"Draft {secret}",
        body=f"draft body {secret}",
    )
    published = await article_service.create_article(
        company_id=company_a.id,
        actor_company_id=company_a.id,
        title=f"Published {secret}",
        body="visible",
    )
    await article_service.publish_article(published.id, company_id=company_a.id)
    other = await article_service.create_article(
        company_id=company_b.id,
        actor_company_id=company_b.id,
        title=f"Other tenant {secret}",
        body=secret,
    )
    await article_service.publish_article(other.id, company_id=company_b.id)

    response = await api_client.get(
        _list_url(company_a.id, secret, status="published"),
        headers=auth_header(employee_a),
    )
    assert response.status_code == 200, response.text
    titles = {item["current_version"]["title"] for item in response.json()["items"]}
    assert f"Published {secret}" in titles
    assert f"Draft {secret}" not in titles
    assert f"Other tenant {secret}" not in titles
    assert draft.id not in {item["id"] for item in response.json()["items"]}

    cross = await api_client.get(
        _list_url(company_b.id, secret),
        headers=auth_header(employee_a),
    )
    assert cross.status_code == 404, cross.text

    other_hr = await api_client.get(
        _list_url(company_b.id, secret),
        headers=auth_header(hr_b),
    )
    assert other_hr.status_code == 200
    other_titles = {item["current_version"]["title"] for item in other_hr.json()["items"]}
    assert f"Published {secret}" not in other_titles
    assert f"Other tenant {secret}" in other_titles


@pytest.mark.asyncio
async def test_employee_search_respects_program_visibility(
    api_client: AsyncClient,
    article_service: ArticleService,
    company_a: Company,
    employee_a: Employee,
) -> None:
    token = uuid4().hex[:10]
    program = await _create_program(company_a.id)
    article = await article_service.create_article(
        company_id=company_a.id,
        actor_company_id=company_a.id,
        title=f"Program only {token}",
        body=f"secret {token}",
        visibility=KnowledgeVisibility.PROGRAM.value,
        program_ids=[program.id],
    )
    await article_service.publish_article(article.id, company_id=company_a.id)

    denied = await api_client.get(
        _list_url(company_a.id, token, status="published"),
        headers=auth_header(employee_a),
    )
    assert denied.status_code == 200, denied.text
    assert denied.json()["items"] == []

    await _assign_employee(
        company_id=company_a.id,
        employee_id=employee_a.id,
        program_id=program.id,
    )
    allowed = await api_client.get(
        _list_url(company_a.id, token, status="published"),
        headers=auth_header(employee_a),
    )
    assert allowed.status_code == 200, allowed.text
    titles = {item["current_version"]["title"] for item in allowed.json()["items"]}
    assert f"Program only {token}" in titles


@pytest.mark.asyncio
async def test_employee_cannot_list_versions(
    api_client: AsyncClient,
    article_service: ArticleService,
    company_a: Company,
    employee_a: Employee,
    hr_a: Employee,
    hr_b: Employee,
    company_b: Company,
) -> None:
    article = await article_service.create_article(
        company_id=company_a.id,
        actor_company_id=company_a.id,
        title="Versioned",
        body="v1 body",
    )
    await article_service.update_article(
        article.id,
        company_id=company_a.id,
        title="Versioned",
        body="v2 body",
        change_summary="second",
    )

    listed = await api_client.get(
        f"/api/v1/knowledge/articles/{article.id}/versions",
        headers=auth_header(hr_a),
    )
    assert listed.status_code == 200, listed.text
    versions = listed.json()["items"]
    assert [row["version"] for row in versions] == [2, 1]
    assert "body" not in versions[0]

    got = await api_client.get(
        f"/api/v1/knowledge/articles/{article.id}/versions/1",
        headers=auth_header(hr_a),
    )
    assert got.status_code == 200
    assert got.json()["body"] == "v1 body"

    emp = await api_client.get(
        f"/api/v1/knowledge/articles/{article.id}/versions",
        headers=auth_header(employee_a),
    )
    assert emp.status_code == 403

    other = await api_client.get(
        f"/api/v1/knowledge/articles/{article.id}/versions",
        headers=auth_header(hr_b),
    )
    assert other.status_code == 404

    restored = await api_client.post(
        f"/api/v1/knowledge/articles/{article.id}/versions/1/restore",
        headers=auth_header(hr_a),
    )
    assert restored.status_code == 200, restored.text
    assert restored.json()["current_version"]["body"] == "v1 body"
    assert restored.json()["current_version"]["version"] == 3

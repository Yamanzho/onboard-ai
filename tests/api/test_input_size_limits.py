"""SEC-M6: authenticated write payloads enforce explicit size limits."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from httpx import AsyncClient
from pydantic import ValidationError as PydanticValidationError

from app.db.enums import AssignmentStatus, ProgressStatus
from app.db.models.assignment import Assignment
from app.db.models.employee import Employee
from app.db.models.onboarding_program import OnboardingProgram
from app.db.models.progress import Progress
from app.db.models.step import Step
from app.schemas.company import CompanyUpdate
from app.schemas.knowledge.article import ArticleCreate, ArticleUpdate
from app.schemas.limits import (
    MAX_ARTICLE_BODY_LENGTH,
    MAX_COMPANY_SETTINGS_JSON_BYTES,
    MAX_PROGRESS_PAYLOAD_JSON_BYTES,
    MAX_STEP_CONTENT_JSON_BYTES,
)
from app.schemas.progress import ProgressCompleteRequest
from app.schemas.step import StepCreate, StepUpdate
from tests.conftest import auth_header, _uow_factory


def _oversized_json_blob(max_bytes: int) -> dict:
    # Compact JSON {"d":"<padding>"} — pad until over limit.
    overhead = len('{"d":""}')
    return {"d": "x" * (max_bytes - overhead + 1)}


# ---------------------------------------------------------------------------
# Schema-level (fast fail-closed checks)
# ---------------------------------------------------------------------------


def test_article_body_over_limit_rejected_by_schema() -> None:
    with pytest.raises(PydanticValidationError):
        ArticleCreate(
            company_id=uuid4(),
            title="Too big",
            body="a" * (MAX_ARTICLE_BODY_LENGTH + 1),
        )
    with pytest.raises(PydanticValidationError):
        ArticleUpdate(body="b" * (MAX_ARTICLE_BODY_LENGTH + 1))


def test_step_content_over_limit_rejected_by_schema() -> None:
    blob = _oversized_json_blob(MAX_STEP_CONTENT_JSON_BYTES)
    with pytest.raises(PydanticValidationError):
        StepCreate(title="Step", content=blob)
    with pytest.raises(PydanticValidationError):
        StepUpdate(content=blob)


def test_progress_payload_over_limit_rejected_by_schema() -> None:
    blob = _oversized_json_blob(MAX_PROGRESS_PAYLOAD_JSON_BYTES)
    with pytest.raises(PydanticValidationError):
        ProgressCompleteRequest(payload=blob)


def test_company_settings_over_limit_rejected_by_schema() -> None:
    blob = _oversized_json_blob(MAX_COMPANY_SETTINGS_JSON_BYTES)
    with pytest.raises(PydanticValidationError):
        CompanyUpdate(settings=blob)


def test_realistic_payloads_accepted_by_schema() -> None:
    ArticleCreate(
        company_id=uuid4(),
        title="VPN setup",
        body="# Guide\n\n" + ("paragraph\n" * 200),
    )
    StepCreate(title="Welcome", content={"body": "Hello " * 500, "links": ["https://example.com"]})
    ProgressCompleteRequest(payload={"ack": True, "answers": {"q1": "a", "q2": "b"}})
    CompanyUpdate(settings={"locale": "en", "flags": {"beta": True}})


# ---------------------------------------------------------------------------
# API-level
# ---------------------------------------------------------------------------


async def test_oversized_article_body_rejected(
    api_client: AsyncClient,
    company_a,
    hr_a: Employee,
) -> None:
    response = await api_client.post(
        "/api/v1/knowledge/articles",
        headers=auth_header(hr_a),
        json={
            "company_id": str(company_a.id),
            "title": "Huge",
            "body": "a" * (MAX_ARTICLE_BODY_LENGTH + 1),
        },
    )
    assert response.status_code == 422, response.text


async def test_normal_article_body_accepted(
    api_client: AsyncClient,
    company_a,
    hr_a: Employee,
) -> None:
    body = "# Onboarding handbook\n\n" + ("Section text. " * 400)
    assert len(body) < MAX_ARTICLE_BODY_LENGTH
    response = await api_client.post(
        "/api/v1/knowledge/articles",
        headers=auth_header(hr_a),
        json={
            "company_id": str(company_a.id),
            "title": "Handbook",
            "body": body,
        },
    )
    assert response.status_code == 201, response.text
    assert response.json()["current_version"]["body"] == body


async def test_oversized_step_content_rejected(
    api_client: AsyncClient,
    company_a,
    hr_a: Employee,
) -> None:
    program = await api_client.post(
        "/api/v1/programs",
        headers=auth_header(hr_a),
        json={"company_id": str(company_a.id), "title": f"Prog {uuid4().hex[:8]}"},
    )
    assert program.status_code == 201, program.text
    program_id = program.json()["id"]

    response = await api_client.post(
        f"/api/v1/programs/{program_id}/steps",
        headers=auth_header(hr_a),
        json={
            "title": "Huge step",
            "step_type": "content",
            "content": _oversized_json_blob(MAX_STEP_CONTENT_JSON_BYTES),
        },
    )
    assert response.status_code == 422, response.text


async def test_normal_step_content_accepted(
    api_client: AsyncClient,
    company_a,
    hr_a: Employee,
) -> None:
    program = await api_client.post(
        "/api/v1/programs",
        headers=auth_header(hr_a),
        json={"company_id": str(company_a.id), "title": f"Prog {uuid4().hex[:8]}"},
    )
    assert program.status_code == 201, program.text
    program_id = program.json()["id"]

    content = {"body": "Welcome aboard! " * 200, "checklist": ["badge", "laptop"]}
    response = await api_client.post(
        f"/api/v1/programs/{program_id}/steps",
        headers=auth_header(hr_a),
        json={"title": "Day 1", "step_type": "content", "content": content},
    )
    assert response.status_code == 201, response.text
    assert response.json()["content"]["body"].startswith("Welcome aboard!")


async def test_oversized_company_settings_rejected(
    api_client: AsyncClient,
    admin_a: Employee,
    company_a,
) -> None:
    response = await api_client.patch(
        f"/api/v1/companies/{company_a.id}",
        headers=auth_header(admin_a),
        json={"settings": _oversized_json_blob(MAX_COMPANY_SETTINGS_JSON_BYTES)},
    )
    assert response.status_code == 422, response.text


async def test_normal_company_settings_accepted(
    api_client: AsyncClient,
    admin_a: Employee,
    company_a,
) -> None:
    settings = {"locale": "ru", "feature_flags": {"kb": True, "bot": True}}
    response = await api_client.patch(
        f"/api/v1/companies/{company_a.id}",
        headers=auth_header(admin_a),
        json={"settings": settings},
    )
    assert response.status_code == 200, response.text
    assert response.json()["settings"] == settings


async def test_oversized_progress_payload_rejected(
    api_client: AsyncClient,
    company_a,
    employee_a: Employee,
) -> None:
    async with _uow_factory() as uow:
        await uow.enter_platform()
        program = await uow.onboarding_programs.create(
            OnboardingProgram(
                company_id=company_a.id,
                title=f"Prog {uuid4().hex[:8]}",
                is_active=True,
            ),
        )
        step = await uow.steps.create(
            Step(
                company_id=company_a.id,
                program_id=program.id,
                title="Ack",
                step_type="ack",
                position=0,
                content={"body": "Please confirm"},
                is_required=True,
            ),
        )
        assignment = await uow.assignments.create(
            Assignment(
                company_id=company_a.id,
                employee_id=employee_a.id,
                program_id=program.id,
                status=AssignmentStatus.IN_PROGRESS.value,
                assigned_at=datetime.now(UTC),
            ),
        )
        progress = await uow.progress.create(
            Progress(
                company_id=company_a.id,
                assignment_id=assignment.id,
                step_id=step.id,
                status=ProgressStatus.NOT_STARTED.value,
                payload={},
            ),
        )
        await uow.commit()
        progress_id = progress.id

    response = await api_client.post(
        f"/api/v1/progress/{progress_id}/complete",
        headers=auth_header(employee_a),
        json={"payload": _oversized_json_blob(MAX_PROGRESS_PAYLOAD_JSON_BYTES)},
    )
    assert response.status_code == 422, response.text


async def test_normal_progress_payload_accepted(
    api_client: AsyncClient,
    company_a,
    employee_a: Employee,
) -> None:
    async with _uow_factory() as uow:
        await uow.enter_platform()
        program = await uow.onboarding_programs.create(
            OnboardingProgram(
                company_id=company_a.id,
                title=f"Prog {uuid4().hex[:8]}",
                is_active=True,
            ),
        )
        step = await uow.steps.create(
            Step(
                company_id=company_a.id,
                program_id=program.id,
                title="Ack",
                step_type="ack",
                position=0,
                content={"body": "Please confirm"},
                is_required=True,
            ),
        )
        assignment = await uow.assignments.create(
            Assignment(
                company_id=company_a.id,
                employee_id=employee_a.id,
                program_id=program.id,
                status=AssignmentStatus.IN_PROGRESS.value,
                assigned_at=datetime.now(UTC),
            ),
        )
        progress = await uow.progress.create(
            Progress(
                company_id=company_a.id,
                assignment_id=assignment.id,
                step_id=step.id,
                status=ProgressStatus.NOT_STARTED.value,
                payload={},
            ),
        )
        await uow.commit()
        progress_id = progress.id

    response = await api_client.post(
        f"/api/v1/progress/{progress_id}/complete",
        headers=auth_header(employee_a),
        json={"payload": {"ack": True}},
    )
    assert response.status_code == 200, response.text
    assert response.json()["payload"] == {"ack": True}
    assert response.json()["status"] == ProgressStatus.COMPLETED.value

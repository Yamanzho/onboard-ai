"""Phase 9H: acknowledgement assignments, version freeze, and ack actions."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from httpx import AsyncClient

from app.db.models.company import Company
from app.db.models.employee import Employee
from app.services.reminder import ReminderService
from tests.api.test_assignment_bulk import _create_employee_api, _publish_program
from tests.api.test_assignment_reminders import _bind_chat, _history
from tests.conftest import _create_employee, auth_header


async def _publish_article(
    client: AsyncClient,
    actor: Employee,
    company_id,
    *,
    title: str | None = None,
    body: str | None = None,
) -> dict:
    created = await client.post(
        "/api/v1/knowledge/articles",
        headers=auth_header(actor),
        json={
            "company_id": str(company_id),
            "title": title or f"Doc {uuid4().hex[:8]}",
            "body": body or "Body v1",
            "visibility": "company",
        },
    )
    assert created.status_code == 201, created.text
    article_id = created.json()["id"]
    published = await client.post(
        f"/api/v1/knowledge/articles/{article_id}/publish",
        headers=auth_header(actor),
    )
    assert published.status_code == 200, published.text
    return published.json()


async def _create_ack(
    client: AsyncClient,
    actor: Employee,
    employee_id: str,
    documents: list[dict],
    **extra,
) -> dict:
    payload = {
        "assignment_type": "acknowledgement",
        "employee_id": employee_id,
        "documents": documents,
        **extra,
    }
    res = await client.post(
        "/api/v1/assignments",
        headers=auth_header(actor),
        json=payload,
    )
    assert res.status_code == 201, res.text
    body = res.json()
    if "items" in body:
        assert body["count"] == 1
        return body["items"][0]
    return body


@pytest.mark.asyncio
async def test_legacy_program_create_defaults_assignment_type(
    api_client: AsyncClient,
    company_a: Company,
    hr_a: Employee,
) -> None:
    program_id = await _publish_program(api_client, hr_a, company_a.id)
    employee = await _create_employee_api(api_client, hr_a, company_a.id)
    res = await api_client.post(
        "/api/v1/assignments",
        headers=auth_header(hr_a),
        json={"employee_id": employee["id"], "program_id": program_id},
    )
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["assignment_type"] == "program"
    assert body["program_id"] == program_id


@pytest.mark.asyncio
async def test_create_one_and_three_documents_preserves_order(
    api_client: AsyncClient,
    company_a: Company,
    hr_a: Employee,
    employee_a: Employee,
) -> None:
    one = await _publish_article(api_client, hr_a, company_a.id, title="Solo")
    created = await _create_ack(
        api_client,
        hr_a,
        str(employee_a.id),
        [{"article_id": one["id"], "position": 1, "is_required": True}],
    )
    assert created["assignment_type"] == "acknowledgement"
    assert created["program_id"] is None
    assert created["acknowledgement"]["total_documents"] == 1
    assert created["acknowledgement"]["required_documents"] == 1

    docs = [
        await _publish_article(api_client, hr_a, company_a.id, title="Code"),
        await _publish_article(api_client, hr_a, company_a.id, title="Security"),
        await _publish_article(api_client, hr_a, company_a.id, title="Remote"),
    ]
    employee = await _create_employee_api(api_client, hr_a, company_a.id)
    created = await _create_ack(
        api_client,
        hr_a,
        employee["id"],
        [
            {"article_id": docs[1]["id"], "position": 2, "is_required": True},
            {"article_id": docs[0]["id"], "position": 1, "is_required": True},
            {"article_id": docs[2]["id"], "position": 3, "is_required": False},
        ],
        priority="important",
    )
    items = await api_client.get(
        f"/api/v1/assignments/{created['id']}/acknowledgements",
        headers=auth_header(hr_a),
    )
    assert items.status_code == 200, items.text
    listed = items.json()["items"]
    assert [row["title"] for row in listed] == ["Code", "Security", "Remote"]
    assert [row["position"] for row in listed] == [1, 2, 3]
    assert [row["is_required"] for row in listed] == [True, True, False]
    assert listed[0]["article_version_id"] == docs[0]["current_version_id"]
    assert listed[1]["article_version_id"] == docs[1]["current_version_id"]
    assert listed[2]["article_version_id"] == docs[2]["current_version_id"]


@pytest.mark.asyncio
async def test_create_rejects_draft_archived_duplicate_and_cross_tenant(
    api_client: AsyncClient,
    company_a: Company,
    company_b: Company,
    hr_a: Employee,
    hr_b: Employee,
    employee_a: Employee,
) -> None:
    draft = await api_client.post(
        "/api/v1/knowledge/articles",
        headers=auth_header(hr_a),
        json={
            "company_id": str(company_a.id),
            "title": "Draft",
            "body": "Draft body",
            "visibility": "company",
        },
    )
    assert draft.status_code == 201
    rejected_draft = await api_client.post(
        "/api/v1/assignments",
        headers=auth_header(hr_a),
        json={
            "assignment_type": "acknowledgement",
            "employee_id": str(employee_a.id),
            "documents": [
                {"article_id": draft.json()["id"], "position": 1, "is_required": True}
            ],
        },
    )
    assert rejected_draft.status_code == 400, rejected_draft.text

    published = await _publish_article(api_client, hr_a, company_a.id)
    archived = await api_client.post(
        f"/api/v1/knowledge/articles/{published['id']}/archive",
        headers=auth_header(hr_a),
    )
    assert archived.status_code == 200, archived.text
    rejected_archived = await api_client.post(
        "/api/v1/assignments",
        headers=auth_header(hr_a),
        json={
            "assignment_type": "acknowledgement",
            "employee_id": str(employee_a.id),
            "documents": [
                {"article_id": published["id"], "position": 1, "is_required": True}
            ],
        },
    )
    assert rejected_archived.status_code == 400, rejected_archived.text

    live = await _publish_article(api_client, hr_a, company_a.id)
    duplicate = await api_client.post(
        "/api/v1/assignments",
        headers=auth_header(hr_a),
        json={
            "assignment_type": "acknowledgement",
            "employee_id": str(employee_a.id),
            "documents": [
                {"article_id": live["id"], "position": 1, "is_required": True},
                {"article_id": live["id"], "position": 2, "is_required": True},
            ],
        },
    )
    assert duplicate.status_code == 422

    foreign = await _publish_article(api_client, hr_b, company_b.id)
    cross = await api_client.post(
        "/api/v1/assignments",
        headers=auth_header(hr_a),
        json={
            "assignment_type": "acknowledgement",
            "employee_id": str(employee_a.id),
            "documents": [
                {"article_id": foreign["id"], "position": 1, "is_required": True}
            ],
        },
    )
    assert cross.status_code == 404


@pytest.mark.asyncio
async def test_version_freeze_and_rollback(
    api_client: AsyncClient,
    company_a: Company,
    hr_a: Employee,
    employee_a: Employee,
) -> None:
    article = await _publish_article(
        api_client, hr_a, company_a.id, title="Policy", body="Version one"
    )
    v1_id = article["current_version_id"]
    first = await _create_ack(
        api_client,
        hr_a,
        str(employee_a.id),
        [{"article_id": article["id"], "position": 1, "is_required": True}],
    )
    items = (
        await api_client.get(
            f"/api/v1/assignments/{first['id']}/acknowledgements",
            headers=auth_header(hr_a),
        )
    ).json()["items"]
    assert items[0]["article_version_id"] == v1_id
    assert items[0]["version"] == 1

    updated = await api_client.put(
        f"/api/v1/knowledge/articles/{article['id']}",
        headers=auth_header(hr_a),
        json={"title": "Policy", "body": "Version two", "change_summary": "v2"},
    )
    assert updated.status_code == 200, updated.text
    v2_id = updated.json()["current_version_id"]
    assert v2_id != v1_id

    viewed = await api_client.get(
        f"/api/v1/assignments/{first['id']}/acknowledgements/{items[0]['id']}",
        headers=auth_header(employee_a),
    )
    assert viewed.status_code == 200, viewed.text
    assert viewed.json()["body"] == "Version one"
    assert viewed.json()["item"]["article_version_id"] == v1_id
    first_after = await api_client.get(
        f"/api/v1/assignments/{first['id']}",
        headers=auth_header(hr_a),
    )
    assert first_after.json()["status"] in {"pending", "in_progress"}

    other = await _create_employee_api(api_client, hr_a, company_a.id)
    second = await _create_ack(
        api_client,
        hr_a,
        other["id"],
        [{"article_id": article["id"], "position": 1, "is_required": True}],
    )
    second_items = (
        await api_client.get(
            f"/api/v1/assignments/{second['id']}/acknowledgements",
            headers=auth_header(hr_a),
        )
    ).json()["items"]
    assert second_items[0]["article_version_id"] == v2_id
    assert second_items[0]["version"] == 2

    restored = await api_client.post(
        f"/api/v1/knowledge/articles/{article['id']}/versions/1/restore",
        headers=auth_header(hr_a),
    )
    assert restored.status_code == 200, restored.text
    v4_id = restored.json()["current_version_id"]
    assert v4_id not in {v1_id, v2_id}

    still_first = (
        await api_client.get(
            f"/api/v1/assignments/{first['id']}/acknowledgements",
            headers=auth_header(hr_a),
        )
    ).json()["items"]
    still_second = (
        await api_client.get(
            f"/api/v1/assignments/{second['id']}/acknowledgements",
            headers=auth_header(hr_a),
        )
    ).json()["items"]
    assert still_first[0]["article_version_id"] == v1_id
    assert still_second[0]["article_version_id"] == v2_id

    third_emp = await _create_employee_api(api_client, hr_a, company_a.id)
    third = await _create_ack(
        api_client,
        hr_a,
        third_emp["id"],
        [{"article_id": article["id"], "position": 1, "is_required": True}],
    )
    third_items = (
        await api_client.get(
            f"/api/v1/assignments/{third['id']}/acknowledgements",
            headers=auth_header(hr_a),
        )
    ).json()["items"]
    assert third_items[0]["article_version_id"] == v4_id


@pytest.mark.asyncio
async def test_open_does_not_acknowledge_and_required_completes(
    api_client: AsyncClient,
    company_a: Company,
    hr_a: Employee,
    employee_a: Employee,
) -> None:
    required = await _publish_article(api_client, hr_a, company_a.id, title="Must")
    optional = await _publish_article(api_client, hr_a, company_a.id, title="Nice")
    assignment = await _create_ack(
        api_client,
        hr_a,
        str(employee_a.id),
        [
            {"article_id": required["id"], "position": 1, "is_required": True},
            {"article_id": optional["id"], "position": 2, "is_required": False},
        ],
    )
    emp = auth_header(employee_a)
    listed = await api_client.get(
        f"/api/v1/assignments/{assignment['id']}/acknowledgements",
        headers=emp,
    )
    assert listed.status_code == 200
    items = listed.json()["items"]
    required_item, optional_item = items[0], items[1]
    assert listed.json()["assignment_status"] == "in_progress"
    assert required_item["acknowledged_at"] is None

    viewed = await api_client.get(
        f"/api/v1/assignments/{assignment['id']}/acknowledgements/{required_item['id']}",
        headers=emp,
    )
    assert viewed.status_code == 200
    assert viewed.json()["item"]["acknowledged_at"] is None
    still = await api_client.get(
        f"/api/v1/assignments/{assignment['id']}",
        headers=emp,
    )
    assert still.json()["status"] == "in_progress"
    assert still.json()["acknowledgement"]["acknowledged_required_count"] == 0

    first = await api_client.post(
        f"/api/v1/assignments/{assignment['id']}/acknowledgements/{required_item['id']}/acknowledge",
        headers=emp,
    )
    assert first.status_code == 200, first.text
    stamped = first.json()["item"]["acknowledged_at"]
    assert stamped is not None
    assert first.json()["assignment_status"] == "completed"
    assert first.json()["acknowledgement"]["completed"] is True

    repeat = await api_client.post(
        f"/api/v1/assignments/{assignment['id']}/acknowledgements/{required_item['id']}/acknowledge",
        headers=emp,
    )
    assert repeat.status_code == 200
    assert repeat.json()["item"]["acknowledged_at"] == stamped
    assert repeat.json()["assignment_status"] == "completed"

    optional_ack = await api_client.post(
        f"/api/v1/assignments/{assignment['id']}/acknowledgements/{optional_item['id']}/acknowledge",
        headers=emp,
    )
    assert optional_ack.status_code == 400
    assert optional_item["acknowledged_at"] is None


@pytest.mark.asyncio
async def test_multiple_required_order_and_cancelled_cannot_ack(
    api_client: AsyncClient,
    company_a: Company,
    hr_a: Employee,
    employee_a: Employee,
) -> None:
    docs = [
        await _publish_article(api_client, hr_a, company_a.id, title=f"D{i}")
        for i in range(1, 4)
    ]
    assignment = await _create_ack(
        api_client,
        hr_a,
        str(employee_a.id),
        [
            {"article_id": docs[0]["id"], "position": 1, "is_required": True},
            {"article_id": docs[1]["id"], "position": 2, "is_required": True},
            {"article_id": docs[2]["id"], "position": 3, "is_required": False},
        ],
    )
    emp = auth_header(employee_a)
    items = (
        await api_client.get(
            f"/api/v1/assignments/{assignment['id']}/acknowledgements",
            headers=emp,
        )
    ).json()["items"]
    first = await api_client.post(
        f"/api/v1/assignments/{assignment['id']}/acknowledgements/{items[0]['id']}/acknowledge",
        headers=emp,
    )
    assert first.json()["assignment_status"] == "in_progress"
    assert first.json()["acknowledgement"]["acknowledged_required_count"] == 1
    second = await api_client.post(
        f"/api/v1/assignments/{assignment['id']}/acknowledgements/{items[1]['id']}/acknowledge",
        headers=emp,
    )
    assert second.json()["assignment_status"] == "completed"
    assert second.json()["item"]["acknowledged_at"] is not None

    other = await _create_employee(
        company_id=company_a.id, role="employee"
    )
    cancellable = await _create_ack(
        api_client,
        hr_a,
        str(other.id),
        [{"article_id": docs[0]["id"], "position": 1, "is_required": True}],
    )
    cancel = await api_client.delete(
        f"/api/v1/assignments/{cancellable['id']}",
        headers=auth_header(hr_a),
    )
    assert cancel.status_code == 204
    other_items = (
        await api_client.get(
            f"/api/v1/assignments/{cancellable['id']}/acknowledgements",
            headers=auth_header(hr_a),
        )
    ).json()["items"]
    blocked = await api_client.post(
        f"/api/v1/assignments/{cancellable['id']}/acknowledgements/{other_items[0]['id']}/acknowledge",
        headers=auth_header(other),
    )
    assert blocked.status_code == 400


@pytest.mark.asyncio
async def test_reassignment_starts_fresh_and_may_capture_new_version(
    api_client: AsyncClient,
    company_a: Company,
    hr_a: Employee,
    employee_a: Employee,
) -> None:
    article = await _publish_article(
        api_client, hr_a, company_a.id, title="Repeat", body="v1"
    )
    first = await _create_ack(
        api_client,
        hr_a,
        str(employee_a.id),
        [{"article_id": article["id"], "position": 1, "is_required": True}],
    )
    item_id = (
        await api_client.get(
            f"/api/v1/assignments/{first['id']}/acknowledgements",
            headers=auth_header(employee_a),
        )
    ).json()["items"][0]["id"]
    ack = await api_client.post(
        f"/api/v1/assignments/{first['id']}/acknowledgements/{item_id}/acknowledge",
        headers=auth_header(employee_a),
    )
    assert ack.json()["assignment_status"] == "completed"
    old_ts = ack.json()["item"]["acknowledged_at"]
    old_version = ack.json()["item"]["article_version_id"]

    updated = await api_client.put(
        f"/api/v1/knowledge/articles/{article['id']}",
        headers=auth_header(hr_a),
        json={"body": "v2", "change_summary": "new"},
    )
    assert updated.status_code == 200
    second = await _create_ack(
        api_client,
        hr_a,
        str(employee_a.id),
        [{"article_id": article["id"], "position": 1, "is_required": True}],
    )
    assert second["id"] != first["id"]
    assert second["status"] == "pending"
    new_items = (
        await api_client.get(
            f"/api/v1/assignments/{second['id']}/acknowledgements",
            headers=auth_header(hr_a),
        )
    ).json()["items"]
    assert new_items[0]["acknowledged_at"] is None
    assert new_items[0]["article_version_id"] != old_version
    old_items = (
        await api_client.get(
            f"/api/v1/assignments/{first['id']}/acknowledgements",
            headers=auth_header(hr_a),
        )
    ).json()["items"]
    assert old_items[0]["acknowledged_at"] == old_ts


@pytest.mark.asyncio
async def test_acknowledgement_reminders_follow_9g(
    api_client: AsyncClient,
    company_a: Company,
    hr_a: Employee,
    employee_a: Employee,
) -> None:
    await _bind_chat(employee_a.id)
    article = await _publish_article(api_client, hr_a, company_a.id, title="InfoSec")
    due = (datetime.now(UTC) + timedelta(days=3)).isoformat()
    assignment = await _create_ack(
        api_client,
        hr_a,
        str(employee_a.id),
        [{"article_id": article["id"], "position": 1, "is_required": True}],
        priority="important",
        due_at=due,
    )
    history = await _history(api_client, hr_a, assignment["id"])
    kinds = [item["source_type"] for item in history["items"]]
    assert "assignment_initial" in kinds

    service = ReminderService()
    morning = datetime(2026, 9, 4, 10, 0, tzinfo=UTC)
    await service.scan_due(now=morning)
    after_scan = await _history(api_client, hr_a, assignment["id"])
    reminder_count = sum(
        1 for item in after_scan["items"] if item["source_type"] == "assignment_reminder"
    )
    assert reminder_count >= 1

    item_id = (
        await api_client.get(
            f"/api/v1/assignments/{assignment['id']}/acknowledgements",
            headers=auth_header(employee_a),
        )
    ).json()["items"][0]["id"]
    done = await api_client.post(
        f"/api/v1/assignments/{assignment['id']}/acknowledgements/{item_id}/acknowledge",
        headers=auth_header(employee_a),
    )
    assert done.json()["assignment_status"] == "completed"
    before = sum(
        1
        for item in (await _history(api_client, hr_a, assignment["id"]))["items"]
        if item["source_type"] == "assignment_reminder"
    )
    await service.scan_due(now=morning + timedelta(days=1))
    after = sum(
        1
        for item in (await _history(api_client, hr_a, assignment["id"]))["items"]
        if item["source_type"] == "assignment_reminder"
    )
    assert after == before

    other = await _create_employee(company_id=company_a.id, role="employee")
    await _bind_chat(other.id)
    blocked = await _create_ack(
        api_client,
        hr_a,
        str(other.id),
        [{"article_id": article["id"], "position": 1, "is_required": True}],
        priority="critical",
    )
    disable = await api_client.post(
        f"/api/v1/assignments/{blocked['id']}/reminders/disable",
        headers=auth_header(other),
    )
    assert disable.status_code == 200, disable.text
    before_disabled = sum(
        1
        for item in (await _history(api_client, hr_a, blocked["id"]))["items"]
        if item["source_type"] == "assignment_reminder"
    )
    await service.scan_due(now=morning + timedelta(days=2))
    after_disabled = sum(
        1
        for item in (await _history(api_client, hr_a, blocked["id"]))["items"]
        if item["source_type"] == "assignment_reminder"
    )
    assert after_disabled == before_disabled
    manual = await api_client.post(
        f"/api/v1/assignments/{blocked['id']}/remind-now",
        headers=auth_header(hr_a),
    )
    assert manual.status_code == 409


@pytest.mark.asyncio
async def test_employee_cannot_access_other_assignment_or_version(
    api_client: AsyncClient,
    company_a: Company,
    hr_a: Employee,
    employee_a: Employee,
) -> None:
    article = await _publish_article(api_client, hr_a, company_a.id, title="Secret")
    owner = await _create_ack(
        api_client,
        hr_a,
        str(employee_a.id),
        [{"article_id": article["id"], "position": 1, "is_required": True}],
    )
    peer_emp = await _create_employee(company_id=company_a.id, role="employee")
    item_id = (
        await api_client.get(
            f"/api/v1/assignments/{owner['id']}/acknowledgements",
            headers=auth_header(hr_a),
        )
    ).json()["items"][0]["id"]
    forbidden_list = await api_client.get(
        f"/api/v1/assignments/{owner['id']}/acknowledgements",
        headers=auth_header(peer_emp),
    )
    assert forbidden_list.status_code == 403
    forbidden_view = await api_client.get(
        f"/api/v1/assignments/{owner['id']}/acknowledgements/{item_id}",
        headers=auth_header(peer_emp),
    )
    assert forbidden_view.status_code == 403
    forbidden_ack = await api_client.post(
        f"/api/v1/assignments/{owner['id']}/acknowledgements/{item_id}/acknowledge",
        headers=auth_header(peer_emp),
    )
    assert forbidden_ack.status_code == 403

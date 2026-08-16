"""AI-12B HTTP conversation history: list, get, archive, POST chat compatibility."""

from __future__ import annotations

from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient

from app.core.ai_constants import MAX_CONVERSATION_TITLE_CHARS
from app.db.enums import ConversationStatus, EmployeeRole
from app.db.models.company import Company
from app.db.models.employee import Employee
from app.services.ai.conversations import ConversationService
from tests.conftest import _create_employee, _uow_factory, auth_header

CHAT_PATH = "/api/v1/ai/chat"
LIST_PATH = "/api/v1/ai/conversations"


@pytest.fixture
def conversations() -> ConversationService:
    return ConversationService(uow_factory=_uow_factory)


def _forbidden_payload_keys(payload: object) -> set[str]:
    blob = str(payload)
    forbidden = {
        "company_id",
        "employee_id",
        "tenant_id",
        "version_id",
        "chunk_index",
        "embedding",
        "score",
    }
    return {key for key in forbidden if key in blob}


@pytest.mark.asyncio
async def test_chat_persists_and_list_get_continue_and_new_thread(
    api_client: AsyncClient,
    employee_a: Employee,
    conversations: ConversationService,
) -> None:
    headers = auth_header(employee_a)
    first = await api_client.post(
        CHAT_PATH, json={"message": "Как оформить отпуск?"}, headers=headers
    )
    assert first.status_code == 200, first.text
    conversation_id = UUID(first.json()["conversation_id"])
    stored = await conversations.get_conversation(
        employee_a.company_id, employee_a.id, conversation_id
    )
    assert stored.title == "Как оформить отпуск?"
    rows = await conversations.list_messages(
        employee_a.company_id, employee_a.id, conversation_id
    )
    assert [row.role for row in rows] == ["user", "assistant"]
    assert rows[0].content == "Как оформить отпуск?"

    listed = await api_client.get(LIST_PATH, headers=headers)
    assert listed.status_code == 200, listed.text
    items = listed.json()["items"]
    assert items[0]["conversation_id"] == str(conversation_id)
    assert items[0]["title"] == "Как оформить отпуск?"
    assert items[0]["message_count"] == 2
    assert items[0]["last_message_preview"]
    assert _forbidden_payload_keys(listed.json()) == set()

    detail = await api_client.get(f"{LIST_PATH}/{conversation_id}", headers=headers)
    assert detail.status_code == 200, detail.text
    body = detail.json()
    assert body["conversation_id"] == str(conversation_id)
    assert [row["role"] for row in body["messages"]] == ["user", "assistant"]
    assert body["messages"][0]["content"] == "Как оформить отпуск?"
    assert "message_id" in body["messages"][0]
    assert _forbidden_payload_keys(body) == set()

    follow = await api_client.post(
        CHAT_PATH,
        json={
            "message": "А кому написать?",
            "conversation_id": str(conversation_id),
        },
        headers=headers,
    )
    assert follow.status_code == 200, follow.text
    assert UUID(follow.json()["conversation_id"]) == conversation_id

    second = await api_client.post(
        CHAT_PATH, json={"message": "Where is the IT desk?"}, headers=headers
    )
    assert second.status_code == 200, second.text
    other_id = UUID(second.json()["conversation_id"])
    assert other_id != conversation_id
    listed_again = await api_client.get(LIST_PATH, headers=headers)
    ids = [item["conversation_id"] for item in listed_again.json()["items"]]
    assert str(other_id) in ids
    assert str(conversation_id) in ids


@pytest.mark.asyncio
async def test_delete_archives_and_hides_from_history(
    api_client: AsyncClient,
    employee_a: Employee,
    conversations: ConversationService,
) -> None:
    headers = auth_header(employee_a)
    created = await api_client.post(
        CHAT_PATH, json={"message": "VPN access"}, headers=headers
    )
    conversation_id = created.json()["conversation_id"]
    deleted = await api_client.delete(f"{LIST_PATH}/{conversation_id}", headers=headers)
    assert deleted.status_code == 204, deleted.text
    listed = await api_client.get(LIST_PATH, headers=headers)
    assert conversation_id not in {
        item["conversation_id"] for item in listed.json()["items"]
    }
    missing = await api_client.get(f"{LIST_PATH}/{conversation_id}", headers=headers)
    assert missing.status_code == 404
    again = await api_client.delete(f"{LIST_PATH}/{conversation_id}", headers=headers)
    assert again.status_code == 404
    stored = await conversations.get_conversation(
        employee_a.company_id, employee_a.id, UUID(conversation_id)
    )
    assert stored.status == ConversationStatus.ARCHIVED.value


@pytest.mark.asyncio
async def test_utf8_titles_and_long_message_truncation(
    api_client: AsyncClient,
    employee_a: Employee,
) -> None:
    headers = auth_header(employee_a)
    kk = await api_client.post(
        CHAT_PATH,
        json={"message": "Демалысты қалай рәсімдеуге болады?"},
        headers=headers,
    )
    assert kk.status_code == 200, kk.text
    listed = await api_client.get(LIST_PATH, headers=headers)
    titles = {item["title"] for item in listed.json()["items"]}
    assert "Демалысты қалай рәсімдеуге болады?" in titles
    long_q = "How do I request leave " + ("and paperwork " * 30)
    long_res = await api_client.post(CHAT_PATH, json={"message": long_q}, headers=headers)
    assert long_res.status_code == 200, long_res.text
    listed2 = await api_client.get(LIST_PATH, headers=headers)
    title = next(
        item["title"]
        for item in listed2.json()["items"]
        if item["conversation_id"] == long_res.json()["conversation_id"]
    )
    assert title is not None
    assert len(title) <= MAX_CONVERSATION_TITLE_CHARS


@pytest.mark.asyncio
async def test_conversations_require_auth_and_reject_selectors(
    api_client: AsyncClient,
    employee_a: Employee,
) -> None:
    assert (await api_client.get(LIST_PATH)).status_code == 401
    headers = auth_header(employee_a)
    created = await api_client.post(
        CHAT_PATH, json={"message": "VPN"}, headers=headers
    )
    conversation_id = created.json()["conversation_id"]
    assert (await api_client.get(f"{LIST_PATH}/{conversation_id}")).status_code == 401
    extra = await api_client.post(
        CHAT_PATH,
        json={
            "message": "VPN",
            "company_id": str(employee_a.company_id),
            "employee_id": str(employee_a.id),
        },
        headers=headers,
    )
    assert extra.status_code == 422
    unknown = await api_client.get(f"{LIST_PATH}/{uuid4()}", headers=headers)
    assert unknown.status_code == 404


@pytest.mark.asyncio
async def test_empty_history_is_empty_list(
    api_client: AsyncClient,
    company_a: Company,
) -> None:
    employee = await _create_employee(
        company_id=company_a.id, role=EmployeeRole.EMPLOYEE.value
    )
    response = await api_client.get(LIST_PATH, headers=auth_header(employee))
    assert response.status_code == 200, response.text
    assert response.json() == {"items": []}

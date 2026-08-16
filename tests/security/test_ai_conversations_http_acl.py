"""AI-12B HTTP IDOR: conversation history is employee- and tenant-scoped."""

from __future__ import annotations

from uuid import UUID

import pytest
from httpx import AsyncClient

from app.db.enums import EmployeeRole
from app.db.models.company import Company
from app.db.models.employee import Employee
from tests.conftest import _create_employee, auth_header

CHAT_PATH = "/api/v1/ai/chat"
LIST_PATH = "/api/v1/ai/conversations"


@pytest.mark.asyncio
async def test_peer_employee_cannot_read_or_delete_conversation(
    api_client: AsyncClient,
    company_a: Company,
    employee_a: Employee,
) -> None:
    owner_headers = auth_header(employee_a)
    created = await api_client.post(
        CHAT_PATH, json={"message": "secret leave policy"}, headers=owner_headers
    )
    assert created.status_code == 200, created.text
    conversation_id = created.json()["conversation_id"]

    peer = await _create_employee(
        company_id=company_a.id, role=EmployeeRole.EMPLOYEE.value
    )
    peer_headers = auth_header(peer)
    listed = await api_client.get(LIST_PATH, headers=peer_headers)
    assert listed.status_code == 200, listed.text
    assert conversation_id not in {
        item["conversation_id"] for item in listed.json()["items"]
    }
    assert "secret leave policy" not in listed.text

    detail = await api_client.get(f"{LIST_PATH}/{conversation_id}", headers=peer_headers)
    assert detail.status_code == 404
    assert "secret leave policy" not in detail.text

    deleted = await api_client.delete(
        f"{LIST_PATH}/{conversation_id}", headers=peer_headers
    )
    assert deleted.status_code == 404

    hijack = await api_client.post(
        CHAT_PATH,
        json={"message": "hijack", "conversation_id": conversation_id},
        headers=peer_headers,
    )
    assert hijack.status_code == 404

    owner_list = await api_client.get(LIST_PATH, headers=owner_headers)
    assert conversation_id in {
        item["conversation_id"] for item in owner_list.json()["items"]
    }


@pytest.mark.asyncio
async def test_cross_tenant_cannot_read_or_delete_conversation(
    api_client: AsyncClient,
    employee_a: Employee,
    employee_b: Employee,
) -> None:
    owner_headers = auth_header(employee_a)
    created = await api_client.post(
        CHAT_PATH, json={"message": "tenant A only"}, headers=owner_headers
    )
    conversation_id = created.json()["conversation_id"]
    other = auth_header(employee_b)

    listed = await api_client.get(LIST_PATH, headers=other)
    assert conversation_id not in {
        item["conversation_id"] for item in listed.json()["items"]
    }
    assert "tenant A only" not in listed.text
    detail = await api_client.get(f"{LIST_PATH}/{conversation_id}", headers=other)
    assert detail.status_code == 404
    assert "tenant A only" not in detail.text
    deleted = await api_client.delete(f"{LIST_PATH}/{conversation_id}", headers=other)
    assert deleted.status_code == 404
    UUID(conversation_id)


@pytest.mark.asyncio
async def test_hr_cannot_read_or_delete_employee_conversation(
    api_client: AsyncClient,
    employee_a: Employee,
    hr_a: Employee,
) -> None:
    owner_headers = auth_header(employee_a)
    created = await api_client.post(
        CHAT_PATH, json={"message": "employee private thread"}, headers=owner_headers
    )
    conversation_id = created.json()["conversation_id"]
    hr_headers = auth_header(hr_a)
    listed = await api_client.get(LIST_PATH, headers=hr_headers)
    assert conversation_id not in {
        item["conversation_id"] for item in listed.json()["items"]
    }
    assert "employee private thread" not in listed.text
    detail = await api_client.get(f"{LIST_PATH}/{conversation_id}", headers=hr_headers)
    assert detail.status_code == 404
    deleted = await api_client.delete(
        f"{LIST_PATH}/{conversation_id}", headers=hr_headers
    )
    assert deleted.status_code == 404

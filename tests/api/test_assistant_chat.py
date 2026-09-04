"""HTTP assistant endpoint keeps /ai/chat unchanged."""

from __future__ import annotations

import pytest
from httpx import AsyncClient

from app.db.models.employee import Employee
from app.services.assistant.messages import GREETING_TEXT, HELP_TEXT
from tests.conftest import auth_header

ASSISTANT = "/api/v1/assistant/chat"
AI_CHAT = "/api/v1/ai/chat"


@pytest.mark.asyncio
async def test_assistant_greeting_and_help_are_deterministic(
    api_client: AsyncClient,
    employee_a: Employee,
) -> None:
    headers = auth_header(employee_a)
    greeting = await api_client.post(
        ASSISTANT, json={"message": "Привет"}, headers=headers
    )
    assert greeting.status_code == 200, greeting.text
    body = greeting.json()
    assert body["intent"] == "greeting"
    assert body["text"] == GREETING_TEXT
    assert body["used_retriever"] is False
    assert body["used_llm"] is False

    help_ = await api_client.post(
        ASSISTANT, json={"message": "Что ты умеешь?"}, headers=headers
    )
    assert help_.status_code == 200
    assert help_.json()["text"] == HELP_TEXT
    assert help_.json()["used_retriever"] is False


@pytest.mark.asyncio
async def test_legacy_ai_chat_still_exists(
    api_client: AsyncClient,
    employee_a: Employee,
) -> None:
    response = await api_client.post(
        AI_CHAT,
        json={"message": "Как оформить отпуск?"},
        headers=auth_header(employee_a),
    )
    assert response.status_code == 200
    body = response.json()
    assert "answer" in body
    assert "no_answer" in body
    assert "intent" not in body


@pytest.mark.asyncio
async def test_assistant_requires_employee_jwt(api_client: AsyncClient) -> None:
    response = await api_client.post(ASSISTANT, json={"message": "Привет"})
    assert response.status_code == 401

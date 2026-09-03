from __future__ import annotations

import asyncio
from uuid import UUID, uuid4

import pytest
from httpx import AsyncClient, Response

from app.api.deps import get_ai_chat_service
from app.bot.api.client import OnboardApiError
from app.bot.services.ai_client import ask_company_knowledge
from app.bot.services.ai_conversation import TelegramConversationStore
from app.core.config import get_settings
from app.core.exceptions import ServiceUnavailableError
from app.db.enums import ConversationStatus
from app.db.uow import UnitOfWork
from app.main import app
from app.services.ai.chat import AIChatService
from app.services.ai.conversations import ConversationService
from app.services.ai.llm import LLMResult
from app.services.ai.retriever import RetrievalHit
from tests.conftest import auth_header

pytestmark = [pytest.mark.api, pytest.mark.security, pytest.mark.telegram]


class _StaticRetriever:
    def __init__(self) -> None:
        self.hit = RetrievalHit(
            chunk_id=uuid4(),
            article_id=uuid4(),
            version_id=uuid4(),
            chunk_index=0,
            article_title="VPN Policy",
            content="Install the approved VPN client from the IT portal.",
            score=0.99,
        )

    async def retrieve(self, *_args, **_kwargs) -> list[RetrievalHit]:
        return [self.hit]


class _CountingLLM:
    model = "counting-test-llm"

    def __init__(
        self,
        *,
        fail_first: bool = False,
        block: bool = False,
    ) -> None:
        self.calls = 0
        self.fail_first = fail_first
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        if not block:
            self.release.set()

    async def generate(self, **_kwargs) -> LLMResult:
        self.calls += 1
        self.started.set()
        await self.release.wait()
        if self.fail_first and self.calls == 1:
            raise ServiceUnavailableError("simulated provider failure")
        return LLMResult(text="Use the IT portal. [S1]", no_answer=False)


class _RealTelegramAIClient:
    """Small bot-facing adapter over the real ASGI API and idempotency path."""

    def __init__(
        self,
        client: AsyncClient,
        *,
        employee,
        service_token: str,
        update_id: int,
    ) -> None:
        self._client = client
        self._employee = employee
        self._service_token = service_token
        self._key = f"telegram-update:{update_id}:ai-chat"
        self.status_codes: list[int] = []

    @property
    def key(self) -> str:
        return self._key

    async def post_ai_chat(
        self,
        message: str,
        *,
        conversation_id: UUID | None = None,
    ) -> dict:
        body = {"message": message}
        if conversation_id is not None:
            body["conversation_id"] = str(conversation_id)
        response = await self._client.post(
            "/api/v1/ai/chat",
            headers={
                **auth_header(self._employee),
                "Idempotency-Key": self._key,
                "X-Telegram-Delivery": "durable",
                "X-Bot-Service-Token": self._service_token,
            },
            json=body,
        )
        self.status_codes.append(response.status_code)
        if response.status_code >= 400:
            payload = response.json()
            raise OnboardApiError(
                "AI API request failed",
                status_code=response.status_code,
                detail=payload.get("detail"),
            )
        payload = response.json()
        assert isinstance(payload, dict)
        return payload


def _install_service(llm: _CountingLLM) -> AIChatService:
    service = AIChatService(
        retriever=_StaticRetriever(),  # type: ignore[arg-type]
        llm_provider=llm,
    )
    app.dependency_overrides[get_ai_chat_service] = lambda: service
    return service


async def _messages(
    *,
    company_id: UUID,
    employee_id: UUID,
    conversation_id: UUID,
):
    return await ConversationService().list_messages(
        company_id,
        employee_id,
        conversation_id,
    )


async def _link_telegram_chat(employee, chat_id: int) -> None:
    async with UnitOfWork() as uow:
        await uow.enter_platform()
        await uow.employees.update(employee.id, telegram_chat_id=chat_id)
        await uow.commit()


async def _assert_single_completed_telegram_turn(
    *,
    employee,
    conversation_id: UUID,
    key: str,
) -> None:
    messages = await _messages(
        company_id=employee.company_id,
        employee_id=employee.id,
        conversation_id=conversation_id,
    )
    assert [message.role for message in messages] == ["user", "assistant"]
    async with UnitOfWork() as uow:
        await uow.enter_tenant(employee.company_id)
        receipts = [
            row
            for row in await uow.idempotency_receipts.list()
            if row.operation == "ai-chat" and row.idempotency_key == key
        ]
        outbox = [
            row
            for row in await uow.telegram_outbound.list()
            if row.source_type == "ai_chat" and row.source_key == key
        ]
    assert len(receipts) == 1
    assert receipts[0].status == "completed"
    assert len(outbox) == 1


@pytest.mark.asyncio
async def test_real_telegram_missing_pointer_recovers_and_replays_once(
    api_client: AsyncClient,
    employee_a,
    telegram_conversation_store: TelegramConversationStore,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    token = "phase-7h-missing-recovery-service-token"
    monkeypatch.setattr(get_settings(), "bot_service_token", token)
    await _link_telegram_chat(employee_a, 7_200)
    stale = uuid4()
    await telegram_conversation_store.set_current_conversation(7_200, stale)
    llm = _CountingLLM()
    _install_service(llm)
    caplog.set_level("INFO", logger="app.kb.chat")
    api = _RealTelegramAIClient(
        api_client,
        employee=employee_a,
        service_token=token,
        update_id=7_200,
    )
    before = await ConversationService().list_conversations(
        employee_a.company_id,
        employee_a.id,
    )
    try:
        first = await ask_company_knowledge(
            api,  # type: ignore[arg-type]
            "VPN access?",
            telegram_user_id=7_200,
            conversations=telegram_conversation_store,
        )
        fresh = await telegram_conversation_store.get_current_conversation(7_200)
        replay = await ask_company_knowledge(
            api,  # type: ignore[arg-type]
            "VPN access?",
            telegram_user_id=7_200,
            conversations=telegram_conversation_store,
        )
        with pytest.raises(OnboardApiError) as mismatch:
            await api.post_ai_chat(
                "Payroll access?",
                conversation_id=fresh,
            )
    finally:
        app.dependency_overrides.pop(get_ai_chat_service, None)

    assert api.status_codes == [200, 200, 409]
    assert mismatch.value.status_code == 409
    assert first == replay
    assert fresh is not None and fresh != stale
    assert llm.calls == 1
    chat_logs = "\n".join(
        record.getMessage()
        for record in caplog.records
        if record.name == "app.kb.chat"
    )
    assert "kb_chat_stale_recovery" in chat_logs
    assert str(stale) in chat_logs
    assert str(fresh) in chat_logs
    assert "VPN access?" not in chat_logs
    after = await ConversationService().list_conversations(
        employee_a.company_id,
        employee_a.id,
    )
    assert len(after) == len(before) + 1
    await _assert_single_completed_telegram_turn(
        employee=employee_a,
        conversation_id=fresh,
        key=api.key,
    )


@pytest.mark.asyncio
async def test_real_telegram_archived_pointer_recovers_to_fresh_conversation(
    api_client: AsyncClient,
    employee_a,
    telegram_conversation_store: TelegramConversationStore,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    token = "phase-7h-archived-recovery-service-token"
    monkeypatch.setattr(get_settings(), "bot_service_token", token)
    await _link_telegram_chat(employee_a, 7_201)
    conversations = ConversationService()
    archived = await conversations.create_conversation(
        employee_a.company_id,
        employee_a.id,
    )
    await conversations.archive_conversation(
        employee_a.company_id,
        employee_a.id,
        archived.id,
    )
    await telegram_conversation_store.set_current_conversation(7_201, archived.id)
    llm = _CountingLLM()
    _install_service(llm)
    api = _RealTelegramAIClient(
        api_client,
        employee=employee_a,
        service_token=token,
        update_id=7_201,
    )
    try:
        reply = await ask_company_knowledge(
            api,  # type: ignore[arg-type]
            "VPN access?",
            telegram_user_id=7_201,
            conversations=telegram_conversation_store,
        )
    finally:
        app.dependency_overrides.pop(get_ai_chat_service, None)

    fresh = await telegram_conversation_store.get_current_conversation(7_201)
    assert api.status_codes == [200]
    assert "Use the IT portal." in reply
    assert fresh is not None and fresh != archived.id
    assert llm.calls == 1
    stored_archived = await conversations.get_conversation(
        employee_a.company_id,
        employee_a.id,
        archived.id,
    )
    assert stored_archived.status == ConversationStatus.ARCHIVED.value
    await _assert_single_completed_telegram_turn(
        employee=employee_a,
        conversation_id=fresh,
        key=api.key,
    )


@pytest.mark.asyncio
async def test_completed_replay_returns_cached_turn_without_second_llm(
    api_client: AsyncClient,
    employee_a,
) -> None:
    llm = _CountingLLM()
    _install_service(llm)
    headers = {
        **auth_header(employee_a),
        "Idempotency-Key": "telegram-update:7001:ai-chat",
    }
    try:
        first = await api_client.post(
            "/api/v1/ai/chat",
            headers=headers,
            json={"message": "How do I get VPN access?"},
        )
        replay = await api_client.post(
            "/api/v1/ai/chat",
            headers=headers,
            json={"message": "How do I get VPN access?"},
        )
    finally:
        app.dependency_overrides.pop(get_ai_chat_service, None)

    assert first.status_code == 200, first.text
    assert replay.status_code == 200, replay.text
    assert replay.json() == first.json()
    assert llm.calls == 1
    conversation_id = UUID(first.json()["conversation_id"])
    messages = await _messages(
        company_id=employee_a.company_id,
        employee_id=employee_a.id,
        conversation_id=conversation_id,
    )
    assert [message.role for message in messages] == ["user", "assistant"]


@pytest.mark.asyncio
async def test_concurrent_same_key_has_one_llm_and_no_integrity_error(
    api_client: AsyncClient,
    employee_a,
) -> None:
    llm = _CountingLLM(block=True)
    _install_service(llm)
    headers = {
        **auth_header(employee_a),
        "Idempotency-Key": "telegram-update:7002:ai-chat",
    }

    async def post() -> Response:
        return await api_client.post(
            "/api/v1/ai/chat",
            headers=headers,
            json={"message": "VPN access?"},
        )

    try:
        winner = asyncio.create_task(post())
        await llm.started.wait()
        duplicate = await post()
        llm.release.set()
        completed = await winner
    finally:
        llm.release.set()
        app.dependency_overrides.pop(get_ai_chat_service, None)

    assert completed.status_code == 200, completed.text
    assert duplicate.status_code == 409
    assert llm.calls == 1


@pytest.mark.asyncio
async def test_concurrent_telegram_stale_recovery_has_one_turn_and_outbox(
    api_client: AsyncClient,
    employee_a,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    token = "phase-7h-concurrent-recovery-service-token"
    monkeypatch.setattr(get_settings(), "bot_service_token", token)
    await _link_telegram_chat(employee_a, 7_202)
    llm = _CountingLLM(block=True)
    _install_service(llm)
    key = "telegram-update:7202:ai-chat"
    headers = {
        **auth_header(employee_a),
        "Idempotency-Key": key,
        "X-Telegram-Delivery": "durable",
        "X-Bot-Service-Token": token,
    }
    body = {
        "message": "VPN access?",
        "conversation_id": str(uuid4()),
    }

    async def post() -> Response:
        return await api_client.post(
            "/api/v1/ai/chat",
            headers=headers,
            json=body,
        )

    try:
        winner = asyncio.create_task(post())
        await llm.started.wait()
        duplicate = await post()
        llm.release.set()
        completed = await winner
    finally:
        llm.release.set()
        app.dependency_overrides.pop(get_ai_chat_service, None)

    assert completed.status_code == 200, completed.text
    assert duplicate.status_code == 409
    assert llm.calls == 1
    await _assert_single_completed_telegram_turn(
        employee=employee_a,
        conversation_id=UUID(completed.json()["conversation_id"]),
        key=key,
    )


@pytest.mark.asyncio
async def test_provider_failure_marks_claim_retryable_and_persists_once(
    api_client: AsyncClient,
    employee_a,
) -> None:
    llm = _CountingLLM(fail_first=True)
    _install_service(llm)
    headers = {
        **auth_header(employee_a),
        "Idempotency-Key": "telegram-update:7003:ai-chat",
    }
    try:
        failed = await api_client.post(
            "/api/v1/ai/chat",
            headers=headers,
            json={"message": "VPN access?"},
        )
        retried = await api_client.post(
            "/api/v1/ai/chat",
            headers=headers,
            json={"message": "VPN access?"},
        )
    finally:
        app.dependency_overrides.pop(get_ai_chat_service, None)

    assert failed.status_code == 503
    assert retried.status_code == 200, retried.text
    assert llm.calls == 2
    messages = await _messages(
        company_id=employee_a.company_id,
        employee_id=employee_a.id,
        conversation_id=UUID(retried.json()["conversation_id"]),
    )
    assert len(messages) == 2


@pytest.mark.asyncio
async def test_same_key_with_different_request_is_rejected(
    api_client: AsyncClient,
    employee_a,
) -> None:
    llm = _CountingLLM()
    _install_service(llm)
    headers = {
        **auth_header(employee_a),
        "Idempotency-Key": "telegram-update:7004:ai-chat",
    }
    try:
        first = await api_client.post(
            "/api/v1/ai/chat",
            headers=headers,
            json={"message": "VPN access?"},
        )
        mismatch = await api_client.post(
            "/api/v1/ai/chat",
            headers=headers,
            json={"message": "Payroll access?"},
        )
    finally:
        app.dependency_overrides.pop(get_ai_chat_service, None)

    assert first.status_code == 200
    assert mismatch.status_code == 409
    assert llm.calls == 1


@pytest.mark.asyncio
async def test_same_raw_key_is_scoped_to_database_employee_identity(
    api_client: AsyncClient,
    employee_a,
    employee_b,
) -> None:
    llm = _CountingLLM()
    _install_service(llm)
    key = "telegram-update:7005:ai-chat"
    try:
        response_a = await api_client.post(
            "/api/v1/ai/chat",
            headers={**auth_header(employee_a), "Idempotency-Key": key},
            json={"message": "VPN access?"},
        )
        response_b = await api_client.post(
            "/api/v1/ai/chat",
            headers={**auth_header(employee_b), "Idempotency-Key": key},
            json={"message": "VPN access?"},
        )
    finally:
        app.dependency_overrides.pop(get_ai_chat_service, None)

    assert response_a.status_code == 200, response_a.text
    assert response_b.status_code == 200, response_b.text
    assert response_a.json()["conversation_id"] != response_b.json()["conversation_id"]
    assert llm.calls == 2


@pytest.mark.asyncio
async def test_keyed_request_cannot_continue_foreign_conversation(
    api_client: AsyncClient,
    employee_a,
    employee_b,
) -> None:
    llm = _CountingLLM()
    _install_service(llm)
    try:
        owned = await api_client.post(
            "/api/v1/ai/chat",
            headers={
                **auth_header(employee_a),
                "Idempotency-Key": "telegram-update:7006:ai-chat",
            },
            json={"message": "VPN access?"},
        )
        foreign = await api_client.post(
            "/api/v1/ai/chat",
            headers={
                **auth_header(employee_b),
                "Idempotency-Key": "telegram-update:7007:ai-chat",
            },
            json={
                "message": "Continue",
                "conversation_id": owned.json()["conversation_id"],
            },
        )
    finally:
        app.dependency_overrides.pop(get_ai_chat_service, None)

    assert owned.status_code == 200
    assert foreign.status_code == 404
    assert llm.calls == 1


@pytest.mark.asyncio
async def test_telegram_recovery_does_not_change_generic_same_company_ownership(
    api_client: AsyncClient,
    employee_a,
    hr_a,
) -> None:
    llm = _CountingLLM()
    _install_service(llm)
    try:
        owned = await api_client.post(
            "/api/v1/ai/chat",
            headers={
                **auth_header(employee_a),
                "Idempotency-Key": "telegram-update:7008:ai-chat",
            },
            json={"message": "VPN access?"},
        )
        foreign = await api_client.post(
            "/api/v1/ai/chat",
            headers={
                **auth_header(hr_a),
                "Idempotency-Key": "telegram-update:7009:ai-chat",
            },
            json={
                "message": "Continue",
                "conversation_id": owned.json()["conversation_id"],
            },
        )
    finally:
        app.dependency_overrides.pop(get_ai_chat_service, None)

    assert owned.status_code == 200
    assert foreign.status_code == 404
    assert llm.calls == 1


@pytest.mark.asyncio
async def test_durable_ai_reply_and_outbox_commit_once_on_replay(
    api_client: AsyncClient,
    employee_a,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    token = "phase-7d-unit-test-bot-service-token"
    monkeypatch.setattr(get_settings(), "bot_service_token", token)
    await _link_telegram_chat(employee_a, 7_100)
    llm = _CountingLLM()
    _install_service(llm)
    key = "telegram-update:7100:ai-chat"
    headers = {
        **auth_header(employee_a),
        "Idempotency-Key": key,
        "X-Telegram-Delivery": "durable",
        "X-Bot-Service-Token": token,
    }
    try:
        first = await api_client.post(
            "/api/v1/ai/chat",
            headers=headers,
            json={"message": "VPN access?"},
        )
        replay = await api_client.post(
            "/api/v1/ai/chat",
            headers=headers,
            json={"message": "VPN access?"},
        )
    finally:
        app.dependency_overrides.pop(get_ai_chat_service, None)

    assert first.status_code == replay.status_code == 200
    assert first.json() == replay.json()
    assert llm.calls == 1
    async with UnitOfWork() as uow:
        await uow.enter_tenant(employee_a.company_id)
        rows = await uow.telegram_outbound.list()
        matching = [
            row
            for row in rows
            if row.source_type == "ai_chat" and row.source_key == key
        ]
        assert len(matching) == 1
        assert matching[0].status == "pending"
        assert "Use the IT portal." in matching[0].body


@pytest.mark.asyncio
async def test_outbox_enqueue_failure_rolls_back_entire_ai_turn(
    api_client: AsyncClient,
    employee_a,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _FailingOutbound:
        async def enqueue_in_uow(self, *_args, **_kwargs):
            raise RuntimeError("simulated outbox insert failure")

    token = "phase-7d-unit-test-bot-service-token"
    monkeypatch.setattr(get_settings(), "bot_service_token", token)
    await _link_telegram_chat(employee_a, 7_101)
    llm = _CountingLLM()
    conversations = ConversationService(
        outbound_service=_FailingOutbound(),  # type: ignore[arg-type]
    )
    service = AIChatService(
        retriever=_StaticRetriever(),  # type: ignore[arg-type]
        llm_provider=llm,
        conversation_service=conversations,
    )
    app.dependency_overrides[get_ai_chat_service] = lambda: service
    before = await conversations.list_conversations(
        employee_a.company_id,
        employee_a.id,
    )
    try:
        with pytest.raises(RuntimeError, match="simulated outbox insert failure"):
            await api_client.post(
                "/api/v1/ai/chat",
                headers={
                    **auth_header(employee_a),
                    "Idempotency-Key": "telegram-update:7101:ai-chat",
                    "X-Telegram-Delivery": "durable",
                    "X-Bot-Service-Token": token,
                },
                json={"message": "VPN access?"},
            )
    finally:
        app.dependency_overrides.pop(get_ai_chat_service, None)

    after = await conversations.list_conversations(
        employee_a.company_id,
        employee_a.id,
    )
    assert len(after) == len(before)
    async with UnitOfWork() as uow:
        await uow.enter_tenant(employee_a.company_id)
        row = await uow.telegram_outbound.get_by_source(
            source_type="ai_chat",
            source_key="telegram-update:7101:ai-chat",
        )
        assert row is None

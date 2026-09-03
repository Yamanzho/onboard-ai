"""Employee-owned AI conversation persistence. Not KB authorization.

Conversation history is DATA. Knowledge-base permissions stay on the
existing article ACL path. Retrieval stays on the existing retriever
boundary. This service does not grant article access, switch tenant,
retrieve knowledge, or call the LLM.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

from sqlalchemy import func
from sqlalchemy.exc import IntegrityError

from app.core.ai_constants import (
    DEFAULT_CONVERSATION_LIST_LIMIT,
    MAX_CHAT_HISTORY_MESSAGES,
    MAX_CONVERSATION_LIST_LIMIT,
    MAX_CONVERSATION_MESSAGE_CHARS,
    MAX_CONVERSATION_PREVIEW_CHARS,
    MAX_CONVERSATION_TITLE_CHARS,
)
from app.core.exceptions import ConflictError, NotFoundError, ValidationError
from app.db.enums import AIMessageRole, ConversationStatus
from app.db.models.ai_conversation import AIConversation
from app.db.models.ai_message import AIMessage
from app.db.models.employee import Employee
from app.db.uow import UnitOfWork
from app.repositories.ai_conversation import ConversationSummaryRow
from app.services.telegram_outbound import TelegramOutboundService
from app.services.tenancy import ensure_same_company

logger = logging.getLogger("app.ai.conversations")

_ALLOWED_ROLES = {AIMessageRole.USER.value, AIMessageRole.ASSISTANT.value}
_NOT_FOUND = "Conversation not found"


class ConversationService:
    """Create, read, archive, and persist messages for the acting employee."""

    def __init__(
        self,
        uow_factory: Callable[[], UnitOfWork] | None = None,
        outbound_service: TelegramOutboundService | None = None,
    ) -> None:
        self._uow_factory = uow_factory or UnitOfWork
        self._outbound = outbound_service or TelegramOutboundService()

    async def create_conversation(
        self,
        actor_company_id: UUID,
        actor_employee_id: UUID,
        *,
        title: str | None = None,
    ) -> AIConversation:
        started = time.perf_counter()
        normalized_title = _validate_title(title)
        async with self._uow_factory() as uow:
            employee = await self._require_actor_employee(
                uow,
                actor_company_id=actor_company_id,
                actor_employee_id=actor_employee_id,
            )
            conversation = await uow.ai_conversations.create(
                AIConversation(
                    company_id=employee.company_id,
                    employee_id=employee.id,
                    title=normalized_title,
                    status=ConversationStatus.ACTIVE.value,
                )
            )
            await uow.commit()
            _log(
                "create",
                company_id=actor_company_id,
                employee_id=actor_employee_id,
                conversation_id=conversation.id,
                result="created",
                started=started,
            )
            return conversation

    async def get_conversation(
        self,
        actor_company_id: UUID,
        actor_employee_id: UUID,
        conversation_id: UUID,
        *,
        include_archived: bool = True,
    ) -> AIConversation:
        async with self._uow_factory() as uow:
            await self._require_actor_employee(
                uow,
                actor_company_id=actor_company_id,
                actor_employee_id=actor_employee_id,
            )
            conversation = await uow.ai_conversations.get_owned(
                conversation_id=conversation_id,
                company_id=actor_company_id,
                employee_id=actor_employee_id,
            )
            if conversation is None:
                raise NotFoundError(_NOT_FOUND)
            if (
                not include_archived
                and conversation.status != ConversationStatus.ACTIVE.value
            ):
                raise NotFoundError(_NOT_FOUND)
            return conversation

    async def get_conversation_with_messages(
        self,
        actor_company_id: UUID,
        actor_employee_id: UUID,
        conversation_id: UUID,
        *,
        offset: int = 0,
        limit: int = MAX_CONVERSATION_LIST_LIMIT,
    ) -> tuple[AIConversation, list[AIMessage]]:
        """Active owned conversation plus chronological messages. One UoW."""
        _validate_page(offset=offset, limit=limit)
        async with self._uow_factory() as uow:
            await self._require_actor_employee(
                uow,
                actor_company_id=actor_company_id,
                actor_employee_id=actor_employee_id,
            )
            conversation = await uow.ai_conversations.get_owned(
                conversation_id=conversation_id,
                company_id=actor_company_id,
                employee_id=actor_employee_id,
            )
            if conversation is None:
                raise NotFoundError(_NOT_FOUND)
            if conversation.status != ConversationStatus.ACTIVE.value:
                raise NotFoundError(_NOT_FOUND)
            messages = await uow.ai_messages.list_for_owned_conversation(
                conversation_id=conversation.id,
                company_id=conversation.company_id,
                offset=offset,
                limit=limit,
            )
            return conversation, messages

    async def list_conversations(
        self,
        actor_company_id: UUID,
        actor_employee_id: UUID,
        *,
        offset: int = 0,
        limit: int = DEFAULT_CONVERSATION_LIST_LIMIT,
    ) -> list[AIConversation]:
        _validate_page(offset=offset, limit=limit)
        async with self._uow_factory() as uow:
            await self._require_actor_employee(
                uow,
                actor_company_id=actor_company_id,
                actor_employee_id=actor_employee_id,
            )
            return await uow.ai_conversations.list_owned(
                company_id=actor_company_id,
                employee_id=actor_employee_id,
                offset=offset,
                limit=limit,
            )

    async def list_conversation_summaries(
        self,
        actor_company_id: UUID,
        actor_employee_id: UUID,
        *,
        offset: int = 0,
        limit: int = DEFAULT_CONVERSATION_LIST_LIMIT,
    ) -> list[ConversationSummaryRow]:
        """Active conversations only, with last-message preview. Not archived."""
        _validate_page(offset=offset, limit=limit)
        async with self._uow_factory() as uow:
            await self._require_actor_employee(
                uow,
                actor_company_id=actor_company_id,
                actor_employee_id=actor_employee_id,
            )
            rows = await uow.ai_conversations.list_owned_summaries(
                company_id=actor_company_id,
                employee_id=actor_employee_id,
                offset=offset,
                limit=limit,
            )
            return [
                ConversationSummaryRow(
                    id=row.id,
                    title=row.title or preview_text(row.last_message_preview),
                    created_at=row.created_at,
                    updated_at=row.updated_at,
                    last_message_preview=preview_text(row.last_message_preview),
                    message_count=row.message_count,
                )
                for row in rows
            ]

    async def archive_conversation(
        self,
        actor_company_id: UUID,
        actor_employee_id: UUID,
        conversation_id: UUID,
    ) -> AIConversation:
        started = time.perf_counter()
        async with self._uow_factory() as uow:
            await self._require_actor_employee(
                uow,
                actor_company_id=actor_company_id,
                actor_employee_id=actor_employee_id,
            )
            conversation = await uow.ai_conversations.get_owned(
                conversation_id=conversation_id,
                company_id=actor_company_id,
                employee_id=actor_employee_id,
            )
            if conversation is None:
                raise NotFoundError(_NOT_FOUND)
            if conversation.status != ConversationStatus.ARCHIVED.value:
                conversation.status = ConversationStatus.ARCHIVED.value
                await uow.session.flush()
                await uow.session.refresh(conversation)
            await uow.commit()
            _log(
                "archive",
                company_id=actor_company_id,
                employee_id=actor_employee_id,
                conversation_id=conversation.id,
                result="archived",
                started=started,
            )
            return conversation

    async def add_message(
        self,
        actor_company_id: UUID,
        actor_employee_id: UUID,
        conversation_id: UUID,
        role: str,
        content: str,
    ) -> AIMessage:
        started = time.perf_counter()
        normalized_role = _validate_role(role)
        normalized_content = _validate_content(content)
        try:
            async with self._uow_factory() as uow:
                await self._require_actor_employee(
                    uow,
                    actor_company_id=actor_company_id,
                    actor_employee_id=actor_employee_id,
                )
                conversation = await uow.ai_conversations.get_owned(
                    conversation_id=conversation_id,
                    company_id=actor_company_id,
                    employee_id=actor_employee_id,
                )
                if conversation is None:
                    raise NotFoundError(_NOT_FOUND)
                if conversation.status == ConversationStatus.ARCHIVED.value:
                    raise ValidationError(
                        "Cannot add messages to an archived conversation"
                    )
                message = await uow.ai_messages.create(
                    AIMessage(
                        conversation_id=conversation.id,
                        company_id=conversation.company_id,
                        role=normalized_role,
                        content=normalized_content,
                    )
                )
                conversation.updated_at = func.now()
                await uow.session.flush()
                await uow.commit()
        except IntegrityError as exc:
            raise ConflictError("Could not persist message") from exc
        _log(
            "add_message",
            company_id=actor_company_id,
            employee_id=actor_employee_id,
            conversation_id=conversation_id,
            message_id=message.id,
            role=normalized_role,
            result="created",
            started=started,
        )
        return message

    async def list_messages(
        self,
        actor_company_id: UUID,
        actor_employee_id: UUID,
        conversation_id: UUID,
        *,
        offset: int = 0,
        limit: int = DEFAULT_CONVERSATION_LIST_LIMIT,
    ) -> list[AIMessage]:
        _validate_page(offset=offset, limit=limit)
        async with self._uow_factory() as uow:
            await self._require_actor_employee(
                uow,
                actor_company_id=actor_company_id,
                actor_employee_id=actor_employee_id,
            )
            conversation = await uow.ai_conversations.get_owned(
                conversation_id=conversation_id,
                company_id=actor_company_id,
                employee_id=actor_employee_id,
            )
            if conversation is None:
                raise NotFoundError(_NOT_FOUND)
            return await uow.ai_messages.list_for_owned_conversation(
                conversation_id=conversation.id,
                company_id=conversation.company_id,
                offset=offset,
                limit=limit,
            )

    async def get_message(
        self,
        actor_company_id: UUID,
        actor_employee_id: UUID,
        message_id: UUID,
    ) -> AIMessage:
        async with self._uow_factory() as uow:
            await self._require_actor_employee(
                uow,
                actor_company_id=actor_company_id,
                actor_employee_id=actor_employee_id,
            )
            message = await uow.ai_messages.get_owned(
                message_id=message_id,
                company_id=actor_company_id,
                employee_id=actor_employee_id,
            )
            if message is None:
                raise NotFoundError("Message not found")
            return message

    async def list_recent_messages(
        self,
        actor_company_id: UUID,
        actor_employee_id: UUID,
        conversation_id: UUID,
        *,
        limit: int = MAX_CHAT_HISTORY_MESSAGES,
    ) -> list[AIMessage]:
        """Newest ``limit`` messages, returned oldest-first for the LLM."""
        _validate_page(offset=0, limit=limit)
        async with self._uow_factory() as uow:
            await self._require_actor_employee(
                uow,
                actor_company_id=actor_company_id,
                actor_employee_id=actor_employee_id,
            )
            conversation = await uow.ai_conversations.get_owned(
                conversation_id=conversation_id,
                company_id=actor_company_id,
                employee_id=actor_employee_id,
            )
            if conversation is None:
                raise NotFoundError(_NOT_FOUND)
            newest_first = await uow.ai_messages.list_recent_for_owned_conversation(
                conversation_id=conversation.id,
                company_id=conversation.company_id,
                limit=limit,
            )
            newest_first.reverse()
            return newest_first

    async def complete_turn(
        self,
        actor_company_id: UUID,
        actor_employee_id: UUID,
        user_content: str,
        assistant_content: str,
        *,
        conversation_id: UUID | None = None,
        citations: list[dict[str, str]] | None = None,
        no_answer: bool = False,
        idempotency_receipt_id: UUID | None = None,
        idempotency_owner_token: UUID | None = None,
        idempotency_response: dict[str, Any] | None = None,
        telegram_outbound_source_key: str | None = None,
        telegram_outbound_body: str | None = None,
    ) -> AIConversation:
        """Persist one user+assistant turn in a single commit. No LLM/retrieval.

        When ``conversation_id`` is omitted a new active conversation is created
        in the same transaction as the messages, so a failed LLM call that never
        reaches this method leaves no empty conversation.
        """
        started = time.perf_counter()
        normalized_user = _validate_content(user_content)
        normalized_assistant = _validate_content(assistant_content)
        stored_citations = _validate_citations(citations)
        title = title_from_user_message(normalized_user)
        idempotency_values = (
            idempotency_receipt_id,
            idempotency_owner_token,
            idempotency_response,
        )
        if any(value is not None for value in idempotency_values) and not all(
            value is not None for value in idempotency_values
        ):
            raise ValueError("Complete idempotency ownership data is required")
        try:
            async with self._uow_factory() as uow:
                employee = await self._require_actor_employee(
                    uow,
                    actor_company_id=actor_company_id,
                    actor_employee_id=actor_employee_id,
                )
                if conversation_id is None:
                    conversation = await uow.ai_conversations.create(
                        AIConversation(
                            company_id=employee.company_id,
                            employee_id=employee.id,
                            title=title,
                            status=ConversationStatus.ACTIVE.value,
                        )
                    )
                else:
                    conversation = await uow.ai_conversations.get_owned(
                        conversation_id=conversation_id,
                        company_id=actor_company_id,
                        employee_id=actor_employee_id,
                    )
                    if conversation is None:
                        raise NotFoundError(_NOT_FOUND)
                    if conversation.status == ConversationStatus.ARCHIVED.value:
                        raise ValidationError(
                            "Cannot add messages to an archived conversation"
                        )
                    if conversation.title is None:
                        conversation.title = title
                turned_at = datetime.now(UTC)
                await uow.ai_messages.create(
                    AIMessage(
                        conversation_id=conversation.id,
                        company_id=conversation.company_id,
                        role=AIMessageRole.USER.value,
                        content=normalized_user,
                        created_at=turned_at,
                        updated_at=turned_at,
                    )
                )
                assistant_at = turned_at + timedelta(microseconds=1)
                await uow.ai_messages.create(
                    AIMessage(
                        conversation_id=conversation.id,
                        company_id=conversation.company_id,
                        role=AIMessageRole.ASSISTANT.value,
                        content=normalized_assistant,
                        citations=stored_citations,
                        no_answer=no_answer,
                        created_at=assistant_at,
                        updated_at=assistant_at,
                    )
                )
                conversation.updated_at = func.now()
                await uow.session.flush()
                await uow.session.refresh(conversation)
                if telegram_outbound_source_key is not None:
                    if telegram_outbound_body is None:
                        raise ValueError("Telegram outbound body is required")
                    if employee.telegram_chat_id is None:
                        raise ConflictError("Employee has no linked Telegram chat")
                    await self._outbound.enqueue_in_uow(
                        uow,
                        company_id=employee.company_id,
                        employee_id=employee.id,
                        chat_id=employee.telegram_chat_id,
                        source_type="ai_chat",
                        source_key=telegram_outbound_source_key,
                        body=telegram_outbound_body,
                    )
                if (
                    idempotency_receipt_id is not None
                    and idempotency_owner_token is not None
                    and idempotency_response is not None
                ):
                    cached_response = dict(idempotency_response)
                    cached_response["conversation_id"] = str(conversation.id)
                    receipt = await uow.idempotency_receipts.complete(
                        receipt_id=idempotency_receipt_id,
                        owner_token=idempotency_owner_token,
                        completed_at=datetime.now(UTC),
                        response=cached_response,
                        company_id=employee.company_id,
                        employee_id=employee.id,
                    )
                    if receipt is None:
                        raise ConflictError("Idempotency claim ownership was lost")
                await uow.commit()
        except IntegrityError as exc:
            raise ConflictError("Could not persist conversation turn") from exc
        _log(
            "complete_turn",
            company_id=actor_company_id,
            employee_id=actor_employee_id,
            conversation_id=conversation.id,
            result="created",
            started=started,
        )
        return conversation

    async def _require_actor_employee(
        self,
        uow: UnitOfWork,
        *,
        actor_company_id: UUID,
        actor_employee_id: UUID,
    ) -> Employee:
        try:
            employee = await uow.enter_employee(actor_employee_id)
        except LookupError as exc:
            raise NotFoundError("Employee not found") from exc
        if employee.id != actor_employee_id:
            raise NotFoundError("Employee not found")
        ensure_same_company(
            resource_company_id=employee.company_id,
            actor_company_id=actor_company_id,
            not_found_message="Employee not found",
        )
        return employee


def _validate_role(role: object) -> str:
    if not isinstance(role, str):
        raise ValidationError("role must be a string")
    normalized = role.strip().lower()
    if normalized not in _ALLOWED_ROLES:
        raise ValidationError("role must be user or assistant")
    return normalized


def _validate_content(content: object) -> str:
    if not isinstance(content, str):
        raise ValidationError("content must be a string")
    stripped = content.strip()
    if not stripped:
        raise ValidationError("content must not be empty")
    if len(stripped) > MAX_CONVERSATION_MESSAGE_CHARS:
        raise ValidationError(
            f"content must be at most {MAX_CONVERSATION_MESSAGE_CHARS} characters"
        )
    return stripped


def _validate_title(title: object) -> str | None:
    if title is None:
        return None
    if not isinstance(title, str):
        raise ValidationError("title must be a string")
    stripped = title.strip()
    if not stripped:
        return None
    if len(stripped) > MAX_CONVERSATION_TITLE_CHARS:
        raise ValidationError(
            f"title must be at most {MAX_CONVERSATION_TITLE_CHARS} characters"
        )
    return stripped


def title_from_user_message(content: str) -> str:
    """Deterministic title from the first user message. No LLM call."""
    collapsed = " ".join(content.split())
    if len(collapsed) <= MAX_CONVERSATION_TITLE_CHARS:
        return collapsed
    return collapsed[: MAX_CONVERSATION_TITLE_CHARS - 1].rstrip() + "…"


def preview_text(content: str | None) -> str | None:
    if not content:
        return None
    collapsed = " ".join(content.split())
    if not collapsed:
        return None
    if len(collapsed) <= MAX_CONVERSATION_PREVIEW_CHARS:
        return collapsed
    return collapsed[: MAX_CONVERSATION_PREVIEW_CHARS - 1].rstrip() + "…"


def _validate_citations(
    citations: object,
) -> list[dict[str, str]] | None:
    if citations is None:
        return None
    if not isinstance(citations, list):
        raise ValidationError("citations must be a list")
    if len(citations) > 20:
        raise ValidationError("citations must contain at most 20 items")
    stored: list[dict[str, str]] = []
    for item in citations:
        if not isinstance(item, dict):
            raise ValidationError("citation must be an object")
        source_id = item.get("source_id")
        title = item.get("title")
        article_id = item.get("article_id")
        if not isinstance(source_id, str) or not source_id.strip():
            raise ValidationError("citation source_id is required")
        if not isinstance(title, str) or not title.strip():
            raise ValidationError("citation title is required")
        if not isinstance(article_id, str) or not article_id.strip():
            raise ValidationError("citation article_id is required")
        stored.append(
            {
                "source_id": source_id.strip(),
                "title": title.strip(),
                "article_id": article_id.strip(),
            }
        )
    return stored or None


def _validate_page(*, offset: int, limit: int) -> None:
    if not isinstance(offset, int) or isinstance(offset, bool) or offset < 0:
        raise ValidationError("offset must be an integer >= 0")
    if (
        not isinstance(limit, int)
        or isinstance(limit, bool)
        or limit < 1
        or limit > MAX_CONVERSATION_LIST_LIMIT
    ):
        raise ValidationError(
            f"limit must be an integer between 1 and {MAX_CONVERSATION_LIST_LIMIT}"
        )


def _log(
    operation: str,
    *,
    company_id: UUID,
    employee_id: UUID,
    conversation_id: UUID,
    result: str,
    started: float,
    message_id: UUID | None = None,
    role: str | None = None,
) -> None:
    duration_ms = (time.perf_counter() - started) * 1000
    logger.info(
        "ai_conversation operation=%s company_id=%s employee_id=%s "
        "conversation_id=%s message_id=%s role=%s result=%s duration_ms=%.1f",
        operation,
        company_id,
        employee_id,
        conversation_id,
        message_id or "",
        role or "",
        result,
        duration_ms,
    )

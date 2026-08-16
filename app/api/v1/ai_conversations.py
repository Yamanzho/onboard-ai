"""AI-12B: employee-owned conversation history HTTP. Not KB authorization."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Query, Response, status

from app.api.auth_deps import EmployeeUser
from app.api.deps import get_conversation_service
from app.api.v1.responses import ERROR_RESPONSES
from app.core.ai_constants import (
    DEFAULT_CONVERSATION_LIST_LIMIT,
    MAX_CONVERSATION_LIST_LIMIT,
)
from app.db.models.ai_message import AIMessage
from app.repositories.ai_conversation import ConversationSummaryRow
from app.schemas.ai import (
    AIChatCitation,
    AIConversationDetailResponse,
    AIConversationListResponse,
    AIConversationMessage,
    AIConversationSummary,
)
from app.services.ai.conversations import ConversationService

router = APIRouter(prefix="/ai", tags=["AI"])

ConversationServiceDep = Annotated[
    ConversationService, Depends(get_conversation_service)
]

_CRUD_RESPONSES = {
    status.HTTP_400_BAD_REQUEST: ERROR_RESPONSES[status.HTTP_400_BAD_REQUEST],
    status.HTTP_401_UNAUTHORIZED: {"description": "Missing or invalid access token"},
    status.HTTP_403_FORBIDDEN: {
        "description": "Authenticated employee required, or Super Admin without impersonation",
    },
    status.HTTP_404_NOT_FOUND: ERROR_RESPONSES[status.HTTP_404_NOT_FOUND],
    status.HTTP_422_UNPROCESSABLE_CONTENT: ERROR_RESPONSES[
        status.HTTP_422_UNPROCESSABLE_CONTENT
    ],
    status.HTTP_500_INTERNAL_SERVER_ERROR: ERROR_RESPONSES[
        status.HTTP_500_INTERNAL_SERVER_ERROR
    ],
}


@router.get(
    "/conversations",
    response_model=AIConversationListResponse,
    summary="List the current employee's AI conversations",
    description=(
        "Returns active conversations owned by the authenticated employee. "
        "Identity comes from the session. Archived threads are omitted. "
        "Metadata only — messages are loaded with GET /conversations/{id}."
    ),
    responses=_CRUD_RESPONSES,
)
async def list_ai_conversations(
    current_user: EmployeeUser,
    service: ConversationServiceDep,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=MAX_CONVERSATION_LIST_LIMIT)] = (
        DEFAULT_CONVERSATION_LIST_LIMIT
    ),
) -> AIConversationListResponse:
    rows = await service.list_conversation_summaries(
        current_user.company_id,
        current_user.id,
        offset=offset,
        limit=limit,
    )
    return AIConversationListResponse(items=[_to_summary(row) for row in rows])


@router.get(
    "/conversations/{conversation_id}",
    response_model=AIConversationDetailResponse,
    summary="Get one owned AI conversation with messages",
    description=(
        "Returns messages for a conversation owned by the authenticated "
        "employee. Unknown, foreign, or archived ids are 404."
    ),
    responses=_CRUD_RESPONSES,
)
async def get_ai_conversation(
    conversation_id: UUID,
    current_user: EmployeeUser,
    service: ConversationServiceDep,
) -> AIConversationDetailResponse:
    conversation, messages = await service.get_conversation_with_messages(
        current_user.company_id,
        current_user.id,
        conversation_id,
    )
    return AIConversationDetailResponse(
        conversation_id=conversation.id,
        title=conversation.title,
        created_at=conversation.created_at,
        updated_at=conversation.updated_at,
        messages=[_to_message(row) for row in messages],
    )


@router.delete(
    "/conversations/{conversation_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Archive an owned AI conversation",
    description=(
        "Soft-deletes (archives) a conversation owned by the authenticated "
        "employee. Archived threads leave history and reject new messages. "
        "Unknown, foreign, or already archived ids are 404."
    ),
    responses=_CRUD_RESPONSES,
)
async def delete_ai_conversation(
    conversation_id: UUID,
    current_user: EmployeeUser,
    service: ConversationServiceDep,
) -> Response:
    await service.get_conversation(
        current_user.company_id,
        current_user.id,
        conversation_id,
        include_archived=False,
    )
    await service.archive_conversation(
        current_user.company_id,
        current_user.id,
        conversation_id,
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


def _to_summary(row: ConversationSummaryRow) -> AIConversationSummary:
    return AIConversationSummary(
        conversation_id=row.id,
        title=row.title,
        created_at=row.created_at,
        updated_at=row.updated_at,
        last_message_preview=row.last_message_preview,
        message_count=row.message_count,
    )


def _to_message(row: AIMessage) -> AIConversationMessage:
    return AIConversationMessage(
        message_id=row.id,
        role=row.role,
        content=row.content,
        created_at=row.created_at,
        citations=_citations_from_stored(row.citations),
        no_answer=bool(row.no_answer),
    )


def _citations_from_stored(raw: object) -> list[AIChatCitation]:
    if not isinstance(raw, list):
        return []
    items: list[AIChatCitation] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        source_id = item.get("source_id")
        title = item.get("title")
        article_id = item.get("article_id")
        if not isinstance(source_id, str) or not isinstance(title, str):
            continue
        try:
            parsed_id = UUID(str(article_id))
        except (TypeError, ValueError):
            continue
        items.append(
            AIChatCitation(source_id=source_id, title=title, article_id=parsed_id)
        )
    return items

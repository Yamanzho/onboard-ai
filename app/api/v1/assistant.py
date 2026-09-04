"""Phase 9I assistant chat. Existing POST /api/v1/ai/chat stays unchanged."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, status

from app.api.auth_deps import EmployeeUser
from app.api.deps import get_assistant_orchestrator
from app.api.v1.ai import _CHAT_RESPONSES, _enforce_ai_chat_rate_limit
from app.core.security import verify_bot_service_token
from app.schemas.ai import AIChatCitation
from app.schemas.assistant import (
    AssistantAssignmentRef,
    AssistantChatRequest,
    AssistantChatResponse,
)
from app.services.assistant.orchestrator import AssistantOrchestrator, AssistantResult

router = APIRouter(prefix="/assistant", tags=["Assistant"])

AssistantDep = Annotated[AssistantOrchestrator, Depends(get_assistant_orchestrator)]


@router.post(
    "/chat",
    response_model=AssistantChatResponse,
    summary="Ask the corporate assistant",
    description=(
        "Intent-routed assistant. Greeting/thanks/help/next-task use DB or "
        "templates. Company knowledge reuses AIChatService / RAG. "
        "POST /api/v1/ai/chat remains the specialized KB endpoint."
    ),
    responses=_CHAT_RESPONSES,
)
async def create_assistant_chat(
    payload: AssistantChatRequest,
    current_user: EmployeeUser,
    service: AssistantDep,
    idempotency_key: Annotated[
        str | None,
        Header(alias="Idempotency-Key", min_length=8, max_length=128),
    ] = None,
    x_telegram_delivery: Annotated[
        str | None,
        Header(alias="X-Telegram-Delivery"),
    ] = None,
    x_bot_service_token: Annotated[
        str | None,
        Header(alias="X-Bot-Service-Token"),
    ] = None,
) -> AssistantChatResponse:
    telegram_delivery = x_telegram_delivery == "durable"
    if x_telegram_delivery is not None and not telegram_delivery:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid Telegram delivery mode",
        )
    if telegram_delivery and not verify_bot_service_token(x_bot_service_token or ""):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
        )

    def enforce_rate_limit() -> None:
        _enforce_ai_chat_rate_limit(
            company_id=current_user.company_id,
            employee_id=current_user.id,
            actor_role=current_user.role,
        )

    result = await service.handle(
        payload.message,
        actor_company_id=current_user.company_id,
        actor_employee_id=current_user.id,
        actor_role=current_user.role,
        conversation_id=payload.conversation_id,
        idempotency_key=idempotency_key,
        telegram_delivery=telegram_delivery,
        on_expensive_call=enforce_rate_limit,
    )
    return _to_http(result)


def _to_http(result: AssistantResult) -> AssistantChatResponse:
    return AssistantChatResponse(
        answer=result.text,
        text=result.text,
        no_answer=result.no_answer,
        intent=result.intent,
        kind=result.kind,
        action=result.action,
        assignment_ids=list(result.assignment_ids),
        assignments=[
            AssistantAssignmentRef(
                id=item.id,
                title=item.title,
                assignment_type=item.assignment_type,
            )
            for item in result.assignments
        ],
        conversation_id=result.conversation_id,
        citations=[
            AIChatCitation(
                source_id=citation.source_id,
                title=citation.title,
                article_id=citation.article_id,
            )
            for citation in result.citations
        ],
        used_retriever=result.used_retriever,
        used_llm=result.used_llm,
    )

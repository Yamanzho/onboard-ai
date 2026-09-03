"""AI-9B: thin HTTP adapter for AIChatService. Not an authorization layer."""

from __future__ import annotations

import logging
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, status

from app.api.auth_deps import EmployeeUser
from app.api.deps import get_ai_chat_service
from app.api.v1.responses import ERROR_RESPONSES
from app.core.config import get_settings
from app.core.rate_limit import is_rate_limited
from app.core.request_id import request_id_log_value
from app.core.security import verify_bot_service_token
from app.schemas.ai import AIChatCitation, AIChatRequest, AIChatResponse
from app.services.ai.chat import AIChatService, ChatAnswer
from app.services.ai.metrics import incr

logger = logging.getLogger("app.kb.chat.http")

router = APIRouter(prefix="/ai", tags=["AI"])

AIChatServiceDep = Annotated[AIChatService, Depends(get_ai_chat_service)]

_CHAT_RESPONSES = {
    status.HTTP_400_BAD_REQUEST: ERROR_RESPONSES[status.HTTP_400_BAD_REQUEST],
    status.HTTP_401_UNAUTHORIZED: {"description": "Missing or invalid access token"},
    status.HTTP_403_FORBIDDEN: {
        "description": "Authenticated employee required, or Super Admin without impersonation",
    },
    status.HTTP_404_NOT_FOUND: ERROR_RESPONSES[status.HTTP_404_NOT_FOUND],
    status.HTTP_409_CONFLICT: ERROR_RESPONSES[status.HTTP_409_CONFLICT],
    status.HTTP_422_UNPROCESSABLE_CONTENT: ERROR_RESPONSES[
        status.HTTP_422_UNPROCESSABLE_CONTENT
    ],
    status.HTTP_429_TOO_MANY_REQUESTS: {
        "description": "AI chat rate limit exceeded",
    },
    status.HTTP_500_INTERNAL_SERVER_ERROR: ERROR_RESPONSES[
        status.HTTP_500_INTERNAL_SERVER_ERROR
    ],
    status.HTTP_503_SERVICE_UNAVAILABLE: ERROR_RESPONSES[
        status.HTTP_503_SERVICE_UNAVAILABLE
    ],
}


@router.post(
    "/chat",
    response_model=AIChatResponse,
    summary="Ask the company knowledge base",
    description=(
        "Employee-facing knowledge-base chat. Tenant and role come from the "
        "authenticated session. The request body is `message` and optional "
        "`conversation_id`. If `conversation_id` is omitted, a new conversation "
        "is created. If provided, the turn continues that thread when it is "
        "owned by the authenticated employee and active. Insufficient "
        "knowledge-base context returns HTTP 200 with no_answer=true."
    ),
    responses=_CHAT_RESPONSES,
)
async def create_ai_chat(
    payload: AIChatRequest,
    current_user: EmployeeUser,
    service: AIChatServiceDep,
    idempotency_key: Annotated[
        str | None,
        Header(
            alias="Idempotency-Key",
            min_length=8,
            max_length=128,
        ),
    ] = None,
    x_telegram_delivery: Annotated[
        str | None,
        Header(alias="X-Telegram-Delivery"),
    ] = None,
    x_bot_service_token: Annotated[
        str | None,
        Header(alias="X-Bot-Service-Token"),
    ] = None,
) -> AIChatResponse:
    telegram_delivery = x_telegram_delivery == "durable"
    if x_telegram_delivery is not None and not telegram_delivery:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid Telegram delivery mode",
        )
    if telegram_delivery and not verify_bot_service_token(
        x_bot_service_token or ""
    ):
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

    if idempotency_key is None:
        enforce_rate_limit()
    result = await service.answer(
        payload.message,
        actor_company_id=current_user.company_id,
        actor_employee_id=current_user.id,
        actor_role=current_user.role,
        conversation_id=payload.conversation_id,
        idempotency_key=idempotency_key,
        on_idempotency_acquired=(
            enforce_rate_limit if idempotency_key is not None else None
        ),
        telegram_delivery=telegram_delivery,
    )
    return _to_http_response(result)


def _to_http_response(result: ChatAnswer) -> AIChatResponse:
    return AIChatResponse(
        answer=result.answer,
        no_answer=result.no_answer,
        conversation_id=result.conversation_id,
        citations=[
            AIChatCitation(
                source_id=citation.source_id,
                title=citation.title,
                article_id=citation.article_id,
            )
            for citation in result.citations
        ],
    )


def _enforce_ai_chat_rate_limit(
    *,
    company_id: UUID,
    employee_id: UUID,
    actor_role: str,
) -> None:
    """Limit expensive LLM calls per authenticated employee. Not ACL."""
    settings = get_settings()
    window = settings.ai_chat_rate_window_seconds
    limited = is_rate_limited(
        f"ai_chat:employee:{employee_id}",
        limit=settings.ai_chat_rate_limit,
        window_seconds=window,
    )
    if limited:
        logger.warning(
            "kb_chat_http request_id=%s company_id=%s employee_id=%s "
            "actor_role=%s result=rate_limited",
            request_id_log_value(),
            company_id,
            employee_id,
            actor_role,
        )
        incr(
            "ai_requests",
            provider="none",
            operation="chat",
            result="rate_limited",
            error_class="rate_limit",
        )
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many AI chat requests. Try again later.",
            headers={"Retry-After": str(window)},
        )

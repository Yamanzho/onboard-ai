from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Request, Response, status
from fastapi.security import OAuth2PasswordRequestForm

from app.api.auth_deps import CurrentUser, EmployeeServiceDep
from app.api.deps import (
    get_idempotency_service,
    get_platform_service,
    get_reminder_service,
    get_telegram_outbound_service,
)
from app.api.v1.responses import ERROR_RESPONSES
from app.core.auth_cookies import (
    clear_auth_cookies,
    read_refresh_cookie,
    set_auth_cookies,
)
from app.core.client_ip import client_ip
from app.core.config import get_settings
from app.core.exceptions import (
    ConflictError,
    ForbiddenError,
    NotFoundError,
    UnauthorizedError,
    ValidationError,
)
from app.core.rate_limit import is_rate_limited
from app.core.request_id import request_id_log_value
from app.core.security import (
    dummy_password_hash,
    hash_password,
    password_hash_needs_upgrade,
    verify_bot_service_token,
    verify_employee_password,
    verify_password,
)
from app.db.enums import EmployeeStatus
from app.db.models.employee import Employee
from app.db.uow import UnitOfWork
from app.schemas.auth import (
    BotInviteAcceptRequest,
    BotOutboundAllowRequest,
    BotOutboundBatchRequest,
    BotOutboundBatchResponse,
    BotOutboundClaimRequest,
    BotOutboundDeliveryResponse,
    BotOutboundFailedRequest,
    BotOutboundSentRequest,
    BotTelegramLoginRequest,
    BotTelegramLoginResponse,
    BotUpdateClaimRequest,
    BotUpdateClaimResponse,
    BotUpdateFinishRequest,
    BotUpdateFinishResponse,
    BrowserSessionResponse,
    CurrentUserResponse,
    PasswordChangeRequest,
    PasswordResetConfirmRequest,
    PasswordResetPreviewRequest,
    PasswordResetPreviewResponse,
    ProfileUpdateRequest,
    RefreshRequest,
    TokenResponse,
)
from app.schemas.reminder import AssignmentOutboundAllowResponse, ReminderScanResponse
from app.schemas.super_admin import (
    InviteAcceptRequest,
    InvitePreviewRequest,
    InvitePreviewResponse,
)
from app.services.employee import EmployeeService
from app.services.idempotency import IdempotencyService
from app.services.platform import PlatformService
from app.services.refresh_session import SUBJECT_EMPLOYEE, RefreshSessionService
from app.services.reminder import ReminderService
from app.services.telegram_outbound import OutboundDelivery, TelegramOutboundService

router = APIRouter(prefix="/auth", tags=["Auth"])
logger = logging.getLogger("app.auth.bot_login")

PlatformServiceDep = Annotated[PlatformService, Depends(get_platform_service)]
IdempotencyServiceDep = Annotated[
    IdempotencyService,
    Depends(get_idempotency_service),
]
TelegramOutboundServiceDep = Annotated[
    TelegramOutboundService,
    Depends(get_telegram_outbound_service),
]
ReminderServiceDep = Annotated[ReminderService, Depends(get_reminder_service)]
_refresh_sessions = RefreshSessionService()
_BOT_AUTH_UNAUTHORIZED_DETAIL = "Could not validate credentials"


async def _issue_tokens(employee: Employee) -> TokenResponse:
    issued = await _refresh_sessions.issue(
        subject_type=SUBJECT_EMPLOYEE,
        subject_id=employee.id,
        role=employee.role,
        company_id=employee.company_id,
    )
    return issued.tokens


def _resolve_refresh_token(request: Request, payload: RefreshRequest | None) -> str | None:
    if payload is not None and payload.refresh_token:
        return payload.refresh_token
    return read_refresh_cookie(request.cookies, kind="tenant")


def _enforce_login_rate_limit(request: Request, *, bucket: str) -> str:
    """Rate-limit password / bot logins by client IP. Returns the resolved IP."""
    settings = get_settings()
    ip = client_ip(request)
    if bucket == "bot_login":
        limit = settings.bot_login_rate_limit
        window = settings.bot_login_rate_window_seconds
    else:
        limit = settings.login_rate_limit
        window = settings.login_rate_window_seconds
    limited = is_rate_limited(
        f"{bucket}:ip:{ip}",
        limit=limit,
        window_seconds=window,
    )
    if limited:
        logger.warning(
            "%s failed reason=rate_limited ip=%s limit=%s window_s=%s",
            bucket,
            ip,
            limit,
            window,
        )
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many login attempts. Try again later.",
            headers={"Retry-After": str(window)},
        )
    return ip


def _enforce_invite_rate_limit(request: Request, *, bucket: str) -> str:
    """Rate-limit invite preview / accept by client IP. Returns the resolved IP."""
    settings = get_settings()
    ip = client_ip(request)
    if bucket == "invite_accept":
        limit = settings.invite_accept_rate_limit
        window = settings.invite_accept_rate_window_seconds
    else:
        limit = settings.invite_preview_rate_limit
        window = settings.invite_preview_rate_window_seconds
    limited = is_rate_limited(
        f"{bucket}:ip:{ip}",
        limit=limit,
        window_seconds=window,
    )
    if limited:
        logger.warning(
            "%s failed reason=rate_limited ip=%s limit=%s window_s=%s",
            bucket,
            ip,
            limit,
            window,
        )
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many invite attempts. Try again later.",
            headers={"Retry-After": str(window)},
        )
    return ip


def _enforce_refresh_rate_limit(request: Request) -> str:
    """Rate-limit tenant refresh by client IP before rotation. Returns IP."""
    settings = get_settings()
    ip = client_ip(request)
    limited = is_rate_limited(
        f"tenant_refresh:ip:{ip}",
        limit=settings.refresh_rate_limit,
        window_seconds=settings.refresh_rate_window_seconds,
    )
    if limited:
        logger.warning(
            "tenant_refresh failed reason=rate_limited ip=%s limit=%s window_s=%s",
            ip,
            settings.refresh_rate_limit,
            settings.refresh_rate_window_seconds,
        )
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many refresh attempts. Try again later.",
            headers={"Retry-After": str(settings.refresh_rate_window_seconds)},
        )
    return ip


async def _authenticate_employee_login(
    employees: EmployeeService,
    employee_id: UUID,
    password: str,
) -> Employee:
    try:
        employee = await employees.get_employee(employee_id)
    except NotFoundError as exc:
        # Timing parity with email path — never reveal whether the UUID exists.
        verify_password(password, dummy_password_hash())
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc

    return await _finalize_employee_login(employees, employee, password)


async def _authenticate_employee_login_by_email(
    employees: EmployeeService,
    email: str,
    password: str,
) -> Employee:
    employee = await employees.get_by_email(email)
    if employee is None:
        verify_password(password, dummy_password_hash())
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return await _finalize_employee_login(employees, employee, password)


async def _finalize_employee_login(
    employees: EmployeeService,
    employee: Employee,
    password: str,
) -> Employee:
    # Password first so invited/archived do not leak via status before auth.
    if not verify_employee_password(password=password, password_hash=employee.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if employee.status == EmployeeStatus.ARCHIVED.value:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Employee is archived",
        )
    if employee.status == EmployeeStatus.INVITED.value:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Please accept your invite and set a password first",
        )
    try:
        await employees.assert_company_active(employee.company_id)
    except ForbiddenError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=exc.message,
        ) from exc

    # Transparent upgrade: legacy PBKDF2 (or stale Argon2 params) → current Argon2id.
    upgrade_hash: str | None = None
    if employee.password_hash and password_hash_needs_upgrade(employee.password_hash):
        upgrade_hash = hash_password(password)

    async with UnitOfWork() as uow:
        await uow.enter_tenant(employee.company_id)
        updates: dict = {"last_login_at": datetime.now(UTC)}
        if upgrade_hash is not None:
            updates["password_hash"] = upgrade_hash
        await uow.employees.update(employee.id, **updates)
        await uow.commit()
    employee.last_login_at = datetime.now(UTC)
    if upgrade_hash is not None:
        employee.password_hash = upgrade_hash
    return employee


@router.post(
    "/login",
    response_model=BrowserSessionResponse,
    summary="Login",
    description=(
        "Exchange employee credentials for an httpOnly cookie session.\n\n"
        "**Username** should be the employee **email** (preferred for web login). "
        "Legacy employee UUID is still accepted for backward compatibility.\n"
        "**Password** is the employee password set via invite, "
        "or the shared MVP auth password (`AUTH_PASSWORD`) for legacy/demo users "
        "when `ALLOW_SHARED_AUTH_PASSWORD` is enabled (disabled in production).\n\n"
        "Raw access/refresh tokens are **not** returned in the JSON body. "
        "The browser must send cookies (`credentials: include`) on subsequent "
        "requests. Bot/service clients should use ``POST /auth/bot/telegram``."
    ),
    responses={
        status.HTTP_401_UNAUTHORIZED: {
            "description": "Invalid email/username or password",
        },
        status.HTTP_403_FORBIDDEN: {
            "description": "Employee is archived, invited, or company deactivated",
        },
        status.HTTP_429_TOO_MANY_REQUESTS: {
            "description": "Login rate limit exceeded",
        },
        status.HTTP_422_UNPROCESSABLE_CONTENT: ERROR_RESPONSES[
            status.HTTP_422_UNPROCESSABLE_CONTENT
        ],
        status.HTTP_500_INTERNAL_SERVER_ERROR: ERROR_RESPONSES[
            status.HTTP_500_INTERNAL_SERVER_ERROR
        ],
    },
)
async def login(
    request: Request,
    response: Response,
    form_data: Annotated[OAuth2PasswordRequestForm, Depends()],
    employees: EmployeeServiceDep,
) -> BrowserSessionResponse:
    _enforce_login_rate_limit(request, bucket="employee_login")
    username = (form_data.username or "").strip()
    if not username:
        verify_password(form_data.password, dummy_password_hash())
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Prefer UUID when the identifier is a valid UUID (legacy clients / tests).
    # Otherwise treat username as email (normalized lower/strip inside lookup).
    try:
        employee_id = UUID(username)
    except ValueError:
        employee = await _authenticate_employee_login_by_email(
            employees,
            username,
            form_data.password,
        )
    else:
        employee = await _authenticate_employee_login(
            employees,
            employee_id,
            form_data.password,
        )

    tokens = await _issue_tokens(employee)
    set_auth_cookies(response, tokens, kind="tenant")
    return BrowserSessionResponse()


@router.post(
    "/bot/telegram",
    response_model=BotTelegramLoginResponse,
    summary="Bot Telegram login",
    description=(
        "Trusted Telegram bot identity exchange.\n\n"
        "Requires header `X-Bot-Service-Token` matching `BOT_SERVICE_TOKEN`. "
        "Resolves the employee by `telegram_user_id` only (shared bot). "
        "Tenant is `employee.company_id` from the database. Optional request "
        "`company_id` is ignored and cannot select a tenant. "
        "`BOT_COMPANY_ID` is not used for identity lookup.\n"
        "Issues a normal employee JWT pair. Does **not** use `AUTH_PASSWORD`.\n\n"
        "The bot then calls protected REST endpoints with the returned "
        "`access_token` as `Authorization: Bearer`, and renews via "
        "`POST /auth/refresh` when the access token expires.\n\n"
        "Rate-limited per client IP (`BOT_LOGIN_RATE_LIMIT` / "
        "`BOT_LOGIN_RATE_WINDOW_SECONDS`)."
    ),
    responses={
        status.HTTP_401_UNAUTHORIZED: {
            "description": "Invalid or missing bot service token",
        },
        status.HTTP_403_FORBIDDEN: {
            "description": "Employee archived, invited, or company deactivated",
        },
        status.HTTP_409_CONFLICT: {
            "description": "Telegram id is linked to multiple active employees",
        },
        status.HTTP_404_NOT_FOUND: ERROR_RESPONSES[status.HTTP_404_NOT_FOUND],
        status.HTTP_429_TOO_MANY_REQUESTS: {
            "description": "Bot login rate limit exceeded",
        },
        status.HTTP_422_UNPROCESSABLE_CONTENT: ERROR_RESPONSES[
            status.HTTP_422_UNPROCESSABLE_CONTENT
        ],
        status.HTTP_500_INTERNAL_SERVER_ERROR: ERROR_RESPONSES[
            status.HTTP_500_INTERNAL_SERVER_ERROR
        ],
    },
)
async def bot_telegram_login(
    request: Request,
    payload: BotTelegramLoginRequest,
    employees: EmployeeServiceDep,
    x_bot_service_token: Annotated[
        str | None,
        Header(
            alias="X-Bot-Service-Token",
            description="Shared bot→API service token (`BOT_SERVICE_TOKEN`).",
        ),
    ] = None,
) -> BotTelegramLoginResponse:
    ip = _enforce_login_rate_limit(request, bucket="bot_login")

    if not verify_bot_service_token(x_bot_service_token or ""):
        logger.warning(
            "bot_login failed request_id=%s source=bot_api "
            "reason=invalid_service_credential ip=%s",
            request_id_log_value(),
            ip,
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=_BOT_AUTH_UNAUTHORIZED_DETAIL,
        )

    try:
        employee = await employees.get_by_telegram_user_id(
            telegram_user_id=payload.telegram_user_id,
        )
    except NotFoundError as exc:
        logger.warning(
            "bot_login failed request_id=%s source=bot_api "
            "reason=identity_not_found ip=%s",
            request_id_log_value(),
            ip,
        )
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    except ConflictError as exc:
        logger.warning(
            "bot_login failed request_id=%s source=bot_api "
            "reason=ambiguous_identity ip=%s",
            request_id_log_value(),
            ip,
        )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(exc),
        ) from exc

    if employee.status == EmployeeStatus.ARCHIVED.value:
        logger.warning(
            "bot_login failed request_id=%s source=bot_api "
            "reason=employee_archived ip=%s",
            request_id_log_value(),
            ip,
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Employee is archived",
        )
    if employee.status == EmployeeStatus.INVITED.value:
        logger.warning(
            "bot_login failed request_id=%s source=bot_api "
            "reason=employee_invited ip=%s",
            request_id_log_value(),
            ip,
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Please accept your invite and set a password first",
        )

    try:
        await employees.assert_company_active(employee.company_id)
    except ForbiddenError as exc:
        logger.warning(
            "bot_login failed request_id=%s source=bot_api "
            "reason=company_access_denied ip=%s",
            request_id_log_value(),
            ip,
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=exc.message,
        ) from exc

    tokens = await _issue_tokens(employee)
    logger.info(
        "bot_login success request_id=%s source=bot_api ip=%s "
        "company_id=%s employee_id=%s role=%s",
        request_id_log_value(),
        ip,
        employee.company_id,
        employee.id,
        employee.role,
    )
    return BotTelegramLoginResponse(
        access_token=tokens.access_token,
        refresh_token=tokens.refresh_token,
        token_type=tokens.token_type,
        employee=CurrentUserResponse.model_validate(employee),
    )


@router.post(
    "/bot/invite/accept",
    response_model=BotTelegramLoginResponse,
    summary="Accept EMPLOYEE invite via Telegram",
    description=(
        "Bot-only: bind Telegram identity to an invited EMPLOYEE using the "
        "invite token from deep link `/start <token>`. "
        "HR/ADMIN invites are rejected. Issues a normal employee JWT pair."
    ),
    responses={
        status.HTTP_401_UNAUTHORIZED: {
            "description": "Invalid or missing bot service token",
        },
        status.HTTP_403_FORBIDDEN: {
            "description": "Telegram already linked or company deactivated",
        },
        status.HTTP_404_NOT_FOUND: ERROR_RESPONSES[status.HTTP_404_NOT_FOUND],
        status.HTTP_429_TOO_MANY_REQUESTS: {
            "description": "Bot login rate limit exceeded",
        },
    },
)
async def bot_accept_invite(
    request: Request,
    payload: BotInviteAcceptRequest,
    platform: PlatformServiceDep,
    x_bot_service_token: Annotated[
        str | None,
        Header(
            alias="X-Bot-Service-Token",
            description="Shared bot→API service token (`BOT_SERVICE_TOKEN`).",
        ),
    ] = None,
) -> BotTelegramLoginResponse:
    ip = _enforce_login_rate_limit(request, bucket="bot_login")

    if not verify_bot_service_token(x_bot_service_token or ""):
        logger.warning(
            "bot_invite_accept failed request_id=%s source=bot_api "
            "reason=invalid_service_credential ip=%s",
            request_id_log_value(),
            ip,
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=_BOT_AUTH_UNAUTHORIZED_DETAIL,
        )

    try:
        employee = await platform.accept_invite_via_telegram(
            token=payload.token,
            telegram_user_id=payload.telegram_user_id,
            telegram_username=payload.telegram_username,
            telegram_chat_id=payload.telegram_chat_id,
        )
    except NotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc
    except ValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    except ConflictError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(exc),
        ) from exc

    try:
        await EmployeeService().assert_company_active(employee.company_id)
    except ForbiddenError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=exc.message,
        ) from exc

    tokens = await _issue_tokens(employee)
    # Never log the invite token — only ids.
    logger.info(
        "bot_invite_accept success request_id=%s source=bot_api ip=%s "
        "company_id=%s employee_id=%s",
        request_id_log_value(),
        ip,
        employee.company_id,
        employee.id,
    )
    return BotTelegramLoginResponse(
        access_token=tokens.access_token,
        refresh_token=tokens.refresh_token,
        token_type=tokens.token_type,
        employee=CurrentUserResponse.model_validate(employee),
    )


@router.post(
    "/bot/updates/claim",
    response_model=BotUpdateClaimResponse,
    summary="Claim Telegram update",
    description="Internal bot-only durable Telegram update claim.",
)
async def claim_bot_update(
    payload: BotUpdateClaimRequest,
    idempotency: IdempotencyServiceDep,
    x_bot_service_token: Annotated[
        str | None,
        Header(alias="X-Bot-Service-Token"),
    ] = None,
) -> BotUpdateClaimResponse:
    if not verify_bot_service_token(x_bot_service_token or ""):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=_BOT_AUTH_UNAUTHORIZED_DETAIL,
        )
    claim = await idempotency.claim_telegram_update(
        update_id=payload.update_id,
        update_type=payload.update_type,
    )
    return BotUpdateClaimResponse(
        state=claim.state,
        receipt_id=claim.receipt_id,
        owner_token=claim.owner_token,
    )


@router.post(
    "/bot/updates/complete",
    response_model=BotUpdateFinishResponse,
    summary="Complete Telegram update",
    description="Internal bot-only completion of an owned Telegram update claim.",
)
async def complete_bot_update(
    payload: BotUpdateFinishRequest,
    idempotency: IdempotencyServiceDep,
    x_bot_service_token: Annotated[
        str | None,
        Header(alias="X-Bot-Service-Token"),
    ] = None,
) -> BotUpdateFinishResponse:
    if not verify_bot_service_token(x_bot_service_token or ""):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=_BOT_AUTH_UNAUTHORIZED_DETAIL,
        )
    updated = await idempotency.complete_telegram_update(
        receipt_id=payload.receipt_id,
        owner_token=payload.owner_token,
    )
    return BotUpdateFinishResponse(updated=updated)


@router.post(
    "/bot/updates/fail",
    response_model=BotUpdateFinishResponse,
    summary="Fail Telegram update",
    description="Internal bot-only retryable failure of an owned update claim.",
)
async def fail_bot_update(
    payload: BotUpdateFinishRequest,
    idempotency: IdempotencyServiceDep,
    x_bot_service_token: Annotated[
        str | None,
        Header(alias="X-Bot-Service-Token"),
    ] = None,
) -> BotUpdateFinishResponse:
    if not verify_bot_service_token(x_bot_service_token or ""):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=_BOT_AUTH_UNAUTHORIZED_DETAIL,
        )
    updated = await idempotency.fail_telegram_update(
        receipt_id=payload.receipt_id,
        owner_token=payload.owner_token,
    )
    return BotUpdateFinishResponse(updated=updated)


def _bot_outbound_response(
    delivery: OutboundDelivery,
) -> BotOutboundDeliveryResponse:
    return BotOutboundDeliveryResponse(
        state=delivery.state,  # type: ignore[arg-type]
        message_id=delivery.message_id,
        owner_token=delivery.owner_token,
        chat_id=delivery.chat_id,
        source_type=delivery.source_type,  # type: ignore[arg-type]
        source_key=delivery.source_key,
        body=delivery.body,
        parse_mode=delivery.parse_mode,  # type: ignore[arg-type]
        attempt_count=delivery.attempt_count,
        telegram_message_id=delivery.telegram_message_id,
    )


@router.post(
    "/bot/outbound/claim",
    response_model=BotOutboundDeliveryResponse,
    summary="Claim durable Telegram outbound by source",
)
async def claim_bot_outbound(
    payload: BotOutboundClaimRequest,
    outbound: TelegramOutboundServiceDep,
    x_bot_service_token: Annotated[
        str | None,
        Header(alias="X-Bot-Service-Token"),
    ] = None,
) -> BotOutboundDeliveryResponse:
    if not verify_bot_service_token(x_bot_service_token or ""):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=_BOT_AUTH_UNAUTHORIZED_DETAIL,
        )
    delivery = await outbound.claim_source(
        source_type=payload.source_type,
        source_key=payload.source_key,
    )
    return _bot_outbound_response(delivery)


@router.post(
    "/bot/outbound/claim-due",
    response_model=BotOutboundBatchResponse,
    summary="Claim a bounded batch of due Telegram outbounds",
)
async def claim_due_bot_outbound(
    payload: BotOutboundBatchRequest,
    outbound: TelegramOutboundServiceDep,
    x_bot_service_token: Annotated[
        str | None,
        Header(alias="X-Bot-Service-Token"),
    ] = None,
) -> BotOutboundBatchResponse:
    if not verify_bot_service_token(x_bot_service_token or ""):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=_BOT_AUTH_UNAUTHORIZED_DETAIL,
        )
    deliveries = await outbound.claim_due_batch(limit=payload.limit)
    return BotOutboundBatchResponse(
        deliveries=[_bot_outbound_response(item) for item in deliveries]
    )


@router.post(
    "/bot/outbound/sent",
    response_model=BotUpdateFinishResponse,
    summary="Acknowledge successful Telegram delivery",
)
async def mark_bot_outbound_sent(
    payload: BotOutboundSentRequest,
    outbound: TelegramOutboundServiceDep,
    x_bot_service_token: Annotated[
        str | None,
        Header(alias="X-Bot-Service-Token"),
    ] = None,
) -> BotUpdateFinishResponse:
    if not verify_bot_service_token(x_bot_service_token or ""):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=_BOT_AUTH_UNAUTHORIZED_DETAIL,
        )
    updated = await outbound.mark_sent(
        message_id=payload.message_id,
        owner_token=payload.owner_token,
        telegram_message_id=payload.telegram_message_id,
    )
    return BotUpdateFinishResponse(updated=updated)


@router.post(
    "/bot/outbound/failed",
    response_model=BotUpdateFinishResponse,
    summary="Record retryable or terminal Telegram failure",
)
async def mark_bot_outbound_failed(
    payload: BotOutboundFailedRequest,
    outbound: TelegramOutboundServiceDep,
    x_bot_service_token: Annotated[
        str | None,
        Header(alias="X-Bot-Service-Token"),
    ] = None,
) -> BotUpdateFinishResponse:
    if not verify_bot_service_token(x_bot_service_token or ""):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=_BOT_AUTH_UNAUTHORIZED_DETAIL,
        )
    updated = await outbound.mark_failed(
        message_id=payload.message_id,
        owner_token=payload.owner_token,
        retryable=payload.retryable,
        error_category=payload.error_category,
        retry_after_seconds=payload.retry_after_seconds,
    )
    return BotUpdateFinishResponse(updated=updated)


@router.post(
    "/bot/outbound/allow",
    response_model=AssignmentOutboundAllowResponse,
    summary="Re-check assignment outbound before send",
)
async def allow_bot_outbound(
    payload: BotOutboundAllowRequest,
    reminders: ReminderServiceDep,
    x_bot_service_token: Annotated[
        str | None,
        Header(alias="X-Bot-Service-Token"),
    ] = None,
) -> AssignmentOutboundAllowResponse:
    if not verify_bot_service_token(x_bot_service_token or ""):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=_BOT_AUTH_UNAUTHORIZED_DETAIL,
        )
    allowed = await reminders.assignment_still_deliverable(
        source_type=payload.source_type,
        source_key=payload.source_key,
    )
    return AssignmentOutboundAllowResponse(allowed=allowed)


@router.post(
    "/bot/reminders/scan",
    response_model=ReminderScanResponse,
    summary="Scan and enqueue due assignment reminders",
)
async def scan_bot_reminders(
    reminders: ReminderServiceDep,
    x_bot_service_token: Annotated[
        str | None,
        Header(alias="X-Bot-Service-Token"),
    ] = None,
) -> ReminderScanResponse:
    if not verify_bot_service_token(x_bot_service_token or ""):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=_BOT_AUTH_UNAUTHORIZED_DETAIL,
        )
    result = await reminders.scan_due()
    return ReminderScanResponse.model_validate(result)


@router.post(
    "/refresh",
    response_model=None,
    summary="Refresh tokens",
    description=(
        "Rotate refresh token and issue a new access/refresh pair via httpOnly "
        "cookies.\n\n"
        "Browser clients should omit the JSON body and rely on the refresh cookie; "
        "the response body is cookie-only (``token_type`` acknowledgement).\n\n"
        "Bot/service clients that present ``refresh_token`` in the JSON body "
        "receive a full token pair in the response (cookies are still set).\n\n"
        "Reuse of a revoked refresh token invalidates the whole session family."
    ),
    responses={
        status.HTTP_401_UNAUTHORIZED: {
            "description": "Invalid, expired, or reused refresh token",
        },
        status.HTTP_403_FORBIDDEN: {
            "description": "Employee is archived, invited, or company deactivated",
        },
        status.HTTP_429_TOO_MANY_REQUESTS: {
            "description": "Refresh rate limit exceeded",
        },
        status.HTTP_422_UNPROCESSABLE_CONTENT: ERROR_RESPONSES[
            status.HTTP_422_UNPROCESSABLE_CONTENT
        ],
        status.HTTP_500_INTERNAL_SERVER_ERROR: ERROR_RESPONSES[
            status.HTTP_500_INTERNAL_SERVER_ERROR
        ],
    },
)
async def refresh_tokens(
    request: Request,
    response: Response,
    employees: EmployeeServiceDep,
    payload: RefreshRequest | None = None,
) -> BrowserSessionResponse | TokenResponse:
    _enforce_refresh_rate_limit(request)
    raw = _resolve_refresh_token(request, payload)
    service_mode = bool(payload is not None and payload.refresh_token)
    if not raw:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid refresh token",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        subject_id, family_id = await _refresh_sessions.begin_rotation(
            raw_refresh=raw,
            subject_type=SUBJECT_EMPLOYEE,
        )
    except UnauthorizedError as exc:
        clear_auth_cookies(response, kind="tenant")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=exc.message,
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc

    employee = await _load_active_employee_for_refresh(employees, subject_id)
    issued = await _refresh_sessions.issue(
        subject_type=SUBJECT_EMPLOYEE,
        subject_id=employee.id,
        role=employee.role,
        company_id=employee.company_id,
        family_id=family_id,
    )
    set_auth_cookies(response, issued.tokens, kind="tenant")
    if service_mode:
        return issued.tokens
    return BrowserSessionResponse()


@router.post(
    "/logout",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Logout",
    description="Revoke the current refresh session and clear auth cookies.",
)
async def logout(
    request: Request,
    response: Response,
    payload: RefreshRequest | None = None,
) -> None:
    raw = _resolve_refresh_token(request, payload)
    await _refresh_sessions.revoke_raw(raw)
    clear_auth_cookies(response, kind="tenant")


@router.post(
    "/logout-all",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Logout all sessions",
    description=(
        "Revoke all refresh sessions for the authenticated employee "
        "and clear auth cookies. Does not affect other users."
    ),
    responses={
        status.HTTP_401_UNAUTHORIZED: {
            "description": "Missing or invalid access token",
        },
        status.HTTP_403_FORBIDDEN: {
            "description": "Employee is archived, invited, or company deactivated",
        },
    },
)
async def logout_all(
    response: Response,
    current_user: CurrentUser,
) -> None:
    await _refresh_sessions.revoke_all_for_subject(
        subject_type=SUBJECT_EMPLOYEE,
        subject_id=current_user.id,
    )
    clear_auth_cookies(response, kind="tenant")


@router.post(
    "/password",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Change password",
    description=(
        "Change the authenticated employee's password. "
        "Requires the current password. Revokes all refresh sessions for this employee."
    ),
    responses={
        status.HTTP_400_BAD_REQUEST: ERROR_RESPONSES[status.HTTP_400_BAD_REQUEST],
        status.HTTP_401_UNAUTHORIZED: {
            "description": "Missing/invalid access token or wrong current password",
        },
        status.HTTP_403_FORBIDDEN: {
            "description": "Employee is archived, invited, or company deactivated",
        },
        status.HTTP_422_UNPROCESSABLE_CONTENT: ERROR_RESPONSES[
            status.HTTP_422_UNPROCESSABLE_CONTENT
        ],
    },
)
async def change_password(
    payload: PasswordChangeRequest,
    response: Response,
    current_user: CurrentUser,
    employees: EmployeeServiceDep,
) -> None:
    try:
        await employees.change_password(
            employee_id=current_user.id,
            company_id=current_user.company_id,
            current_password=payload.current_password,
            new_password=payload.new_password,
        )
    except UnauthorizedError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=exc.message,
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc
    except ValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    except ForbiddenError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=exc.message,
        ) from exc
    clear_auth_cookies(response, kind="tenant")


def _current_user_response(
    employee: Employee,
    *,
    company_name: str | None = None,
    company_description: str | None = None,
) -> CurrentUserResponse:
    base = CurrentUserResponse.model_validate(employee)
    return base.model_copy(
        update={
            "telegram_connected": bool(
                employee.telegram_username or employee.telegram_chat_id
            ),
            "company_name": company_name,
            "company_description": company_description,
            "hired_at": employee.hired_at,
        }
    )


async def _load_active_employee_for_refresh(
    employees: EmployeeService,
    employee_id: UUID,
) -> Employee:
    try:
        employee = await employees.get_employee(employee_id)
    except NotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid refresh token",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc

    if employee.status == EmployeeStatus.ARCHIVED.value:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Employee is archived",
        )
    if employee.status == EmployeeStatus.INVITED.value:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Please accept your invite and set a password first",
        )
    try:
        await employees.assert_company_active(employee.company_id)
    except ForbiddenError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=exc.message,
        ) from exc
    return employee


@router.get(
    "/me",
    response_model=CurrentUserResponse,
    summary="Current user",
    description="Return the employee bound to the current Bearer access token.",
    responses={
        status.HTTP_401_UNAUTHORIZED: {
            "description": "Missing or invalid access token",
        },
        status.HTTP_403_FORBIDDEN: {
            "description": "Employee is archived or company deactivated",
        },
        status.HTTP_422_UNPROCESSABLE_CONTENT: ERROR_RESPONSES[
            status.HTTP_422_UNPROCESSABLE_CONTENT
        ],
        status.HTTP_500_INTERNAL_SERVER_ERROR: ERROR_RESPONSES[
            status.HTTP_500_INTERNAL_SERVER_ERROR
        ],
    },
)
async def me(
    current_user: CurrentUser,
    employees: EmployeeServiceDep,
) -> CurrentUserResponse:
    summary = await employees.get_company_summary(current_user.company_id)
    return _current_user_response(
        current_user,
        company_name=summary["name"] if summary else None,
        company_description=summary["description"] if summary else None,
    )


@router.patch(
    "/me",
    response_model=CurrentUserResponse,
    summary="Update current user profile",
    description=(
        "Update allowed personal fields for the authenticated employee "
        "(full_name, email). Role, company, status, and telegram binding "
        "cannot be changed here."
    ),
    responses={
        status.HTTP_400_BAD_REQUEST: ERROR_RESPONSES[status.HTTP_400_BAD_REQUEST],
        status.HTTP_401_UNAUTHORIZED: {
            "description": "Missing or invalid access token",
        },
        status.HTTP_403_FORBIDDEN: {
            "description": "Employee is archived, invited, or company deactivated",
        },
        status.HTTP_422_UNPROCESSABLE_CONTENT: ERROR_RESPONSES[
            status.HTTP_422_UNPROCESSABLE_CONTENT
        ],
    },
)
async def update_me(
    payload: ProfileUpdateRequest,
    current_user: CurrentUser,
    employees: EmployeeServiceDep,
) -> CurrentUserResponse:
    try:
        employee = await employees.update_own_profile(
            employee_id=current_user.id,
            company_id=current_user.company_id,
            **payload.model_dump(exclude_unset=True),
        )
    except ValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(exc),
        ) from exc
    except ForbiddenError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=exc.message,
        ) from exc
    summary = await employees.get_company_summary(employee.company_id)
    return _current_user_response(
        employee,
        company_name=summary["name"] if summary else None,
        company_description=summary["description"] if summary else None,
    )


@router.post(
    "/password/reset/preview",
    response_model=PasswordResetPreviewResponse,
    summary="Preview password reset token",
    description=(
        "Preview a password-reset token from the JSON body "
        "(not the URL path) so access logs do not capture the credential."
    ),
    responses={
        status.HTTP_429_TOO_MANY_REQUESTS: {
            "description": "Invite preview rate limit exceeded",
        },
    },
)
async def preview_password_reset(
    request: Request,
    payload: PasswordResetPreviewRequest,
    employees: EmployeeServiceDep,
) -> PasswordResetPreviewResponse:
    _enforce_invite_rate_limit(request, bucket="invite_preview")
    try:
        data = await employees.preview_password_reset(payload.token)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return PasswordResetPreviewResponse.model_validate(data)


@router.post(
    "/password/reset/confirm",
    response_model=CurrentUserResponse,
    summary="Confirm password reset",
    description=(
        "Set a new password using a one-time reset token. "
        "Revokes all refresh sessions for the employee."
    ),
    responses={
        status.HTTP_429_TOO_MANY_REQUESTS: {
            "description": "Invite accept rate limit exceeded",
        },
    },
)
async def confirm_password_reset(
    request: Request,
    payload: PasswordResetConfirmRequest,
    employees: EmployeeServiceDep,
) -> CurrentUserResponse:
    _enforce_invite_rate_limit(request, bucket="invite_accept")
    try:
        employee = await employees.confirm_password_reset(
            token=payload.token,
            new_password=payload.new_password,
        )
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    summary = await employees.get_company_summary(employee.company_id)
    return _current_user_response(
        employee,
        company_name=summary["name"] if summary else None,
        company_description=summary["description"] if summary else None,
    )


@router.post(
    "/invite/preview",
    response_model=InvitePreviewResponse,
    summary="Preview employee invite",
    description=(
        "Preview an invite using the secret token in the JSON body "
        "(not the URL path) so access logs / proxies do not capture the credential."
    ),
    responses={
        status.HTTP_429_TOO_MANY_REQUESTS: {
            "description": "Invite preview rate limit exceeded",
        },
    },
)
async def preview_invite(
    request: Request,
    payload: InvitePreviewRequest,
    platform: PlatformServiceDep,
) -> InvitePreviewResponse:
    _enforce_invite_rate_limit(request, bucket="invite_preview")
    try:
        return await platform.preview_invite(payload.token)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.post(
    "/invite/accept",
    response_model=CurrentUserResponse,
    summary="Accept invite and set password",
    responses={
        status.HTTP_429_TOO_MANY_REQUESTS: {
            "description": "Invite accept rate limit exceeded",
        },
    },
)
async def accept_invite(
    request: Request,
    payload: InviteAcceptRequest,
    platform: PlatformServiceDep,
) -> CurrentUserResponse:
    _enforce_invite_rate_limit(request, bucket="invite_accept")
    try:
        employee = await platform.accept_invite(payload)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return CurrentUserResponse.model_validate(employee)


# Re-export for importers that expect guards alongside the router.
__all__ = [
    "accept_invite",
    "bot_accept_invite",
    "bot_telegram_login",
    "change_password",
    "confirm_password_reset",
    "login",
    "logout",
    "logout_all",
    "me",
    "preview_invite",
    "preview_password_reset",
    "refresh_tokens",
    "router",
    "update_me",
]

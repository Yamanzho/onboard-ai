from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from fastapi.security import OAuth2PasswordRequestForm

from app.api.auth_deps import CurrentUser, EmployeeServiceDep
from app.api.deps import get_platform_service
from app.api.v1.responses import ERROR_RESPONSES
from app.core.config import get_settings
from app.core.exceptions import NotFoundError, ValidationError
from app.core.rate_limit import is_rate_limited
from app.core.security import (
    InvalidTokenError,
    create_access_token,
    create_refresh_token,
    decode_token,
    verify_bot_service_token,
    verify_employee_password,
)
from app.db.enums import EmployeeStatus
from app.db.models.employee import Employee
from app.db.uow import UnitOfWork
from app.schemas.auth import (
    BotTelegramLoginRequest,
    BotTelegramLoginResponse,
    CurrentUserResponse,
    RefreshRequest,
    TokenResponse,
)
from app.schemas.super_admin import InviteAcceptRequest, InvitePreviewResponse
from app.services.employee import EmployeeService
from app.services.platform import PlatformService

router = APIRouter(prefix="/auth", tags=["Auth"])
logger = logging.getLogger("app.auth.bot_login")

PlatformServiceDep = Annotated[PlatformService, Depends(get_platform_service)]


def _issue_tokens(employee: Employee) -> TokenResponse:
    return TokenResponse(
        access_token=create_access_token(
            subject=employee.id,
            role=employee.role,
            company_id=employee.company_id,
        ),
        refresh_token=create_refresh_token(
            subject=employee.id,
            role=employee.role,
            company_id=employee.company_id,
        ),
        token_type="bearer",
    )


async def _authenticate_employee_login(
    employees: EmployeeService,
    employee_id: UUID,
    password: str,
) -> Employee:
    try:
        employee = await employees.get_employee(employee_id)
    except NotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
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
    if not verify_employee_password(password=password, password_hash=employee.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )

    async with UnitOfWork() as uow:
        await uow.employees.update(employee_id, last_login_at=datetime.now(UTC))
        await uow.commit()
    employee.last_login_at = datetime.now(UTC)
    return employee


def _client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    if request.client is not None:
        return request.client.host
    return "unknown"


def _enforce_bot_login_rate_limit(request: Request) -> str:
    """Rate-limit bot telegram-login by client IP. Returns the resolved IP."""
    settings = get_settings()
    ip = _client_ip(request)
    limited = is_rate_limited(
        f"bot_login:ip:{ip}",
        limit=settings.bot_login_rate_limit,
        window_seconds=settings.bot_login_rate_window_seconds,
    )
    if limited:
        logger.warning(
            "bot_login failed reason=rate_limited ip=%s limit=%s window_s=%s",
            ip,
            settings.bot_login_rate_limit,
            settings.bot_login_rate_window_seconds,
        )
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many bot login attempts. Try again later.",
            headers={"Retry-After": str(settings.bot_login_rate_window_seconds)},
        )
    return ip


@router.post(
    "/login",
    response_model=TokenResponse,
    summary="Login",
    description=(
        "Exchange employee credentials for JWT access and refresh tokens.\n\n"
        "**Username** must be the employee UUID.\n"
        "**Password** is the employee password set via invite, "
        "or the shared MVP auth password (`AUTH_PASSWORD`) for legacy/demo users.\n\n"
        "Use the returned `access_token` with Swagger **Authorize** "
        "(OAuth2 password flow / Bearer)."
    ),
    responses={
        status.HTTP_401_UNAUTHORIZED: {
            "description": "Invalid username or password",
        },
        status.HTTP_403_FORBIDDEN: {
            "description": "Employee is archived",
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
    form_data: Annotated[OAuth2PasswordRequestForm, Depends()],
    employees: EmployeeServiceDep,
) -> TokenResponse:
    try:
        employee_id = UUID(form_data.username)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc

    employee = await _authenticate_employee_login(
        employees,
        employee_id,
        form_data.password,
    )
    return _issue_tokens(employee)


@router.post(
    "/bot/telegram",
    response_model=BotTelegramLoginResponse,
    summary="Bot Telegram login",
    description=(
        "Trusted Telegram bot identity exchange.\n\n"
        "Requires header `X-Bot-Service-Token` matching `BOT_SERVICE_TOKEN`. "
        "Resolves the employee by `(company_id, telegram_user_id)` and issues "
        "a normal employee JWT pair. Does **not** use `AUTH_PASSWORD`.\n\n"
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
            "description": "Employee is archived",
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
    ip = _enforce_bot_login_rate_limit(request)

    if not verify_bot_service_token(x_bot_service_token or ""):
        logger.warning(
            "bot_login failed reason=invalid_service_token ip=%s "
            "company_id=%s telegram_user_id=%s",
            ip,
            payload.company_id,
            payload.telegram_user_id,
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid bot service token",
        )

    try:
        employee = await employees.get_by_telegram_user_id(
            company_id=payload.company_id,
            telegram_user_id=payload.telegram_user_id,
        )
    except NotFoundError as exc:
        logger.warning(
            "bot_login failed reason=employee_not_found ip=%s "
            "company_id=%s telegram_user_id=%s",
            ip,
            payload.company_id,
            payload.telegram_user_id,
        )
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        ) from exc

    if employee.status == EmployeeStatus.ARCHIVED.value:
        logger.warning(
            "bot_login failed reason=employee_archived ip=%s "
            "company_id=%s telegram_user_id=%s employee_id=%s",
            ip,
            payload.company_id,
            payload.telegram_user_id,
            employee.id,
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Employee is archived",
        )

    tokens = _issue_tokens(employee)
    logger.info(
        "bot_login success ip=%s company_id=%s telegram_user_id=%s "
        "employee_id=%s role=%s",
        ip,
        employee.company_id,
        payload.telegram_user_id,
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
    "/refresh",
    response_model=TokenResponse,
    summary="Refresh tokens",
    description="Issue a new access/refresh token pair using a valid refresh token.",
    responses={
        status.HTTP_401_UNAUTHORIZED: {
            "description": "Invalid or expired refresh token",
        },
        status.HTTP_403_FORBIDDEN: {
            "description": "Employee is archived",
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
    payload: RefreshRequest,
    employees: EmployeeServiceDep,
) -> TokenResponse:
    try:
        token_payload = decode_token(payload.refresh_token, expected_type="refresh")
        employee_id = UUID(token_payload["sub"])
    except (InvalidTokenError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid refresh token",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc

    employee = await _load_active_employee_for_refresh(employees, employee_id)
    return _issue_tokens(employee)


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
            "description": "Employee is archived",
        },
        status.HTTP_422_UNPROCESSABLE_CONTENT: ERROR_RESPONSES[
            status.HTTP_422_UNPROCESSABLE_CONTENT
        ],
        status.HTTP_500_INTERNAL_SERVER_ERROR: ERROR_RESPONSES[
            status.HTTP_500_INTERNAL_SERVER_ERROR
        ],
    },
)
async def me(current_user: CurrentUser) -> CurrentUserResponse:
    return CurrentUserResponse.model_validate(current_user)


@router.get(
    "/invite/{token}",
    response_model=InvitePreviewResponse,
    summary="Preview employee invite",
)
async def preview_invite(token: str, platform: PlatformServiceDep) -> InvitePreviewResponse:
    try:
        return await platform.preview_invite(token)
    except NotFoundError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ValidationError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.post(
    "/invite/accept",
    response_model=CurrentUserResponse,
    summary="Accept invite and set password",
)
async def accept_invite(
    payload: InviteAcceptRequest,
    platform: PlatformServiceDep,
) -> CurrentUserResponse:
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
    "bot_telegram_login",
    "login",
    "me",
    "preview_invite",
    "refresh_tokens",
    "router",
]

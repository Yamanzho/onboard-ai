from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from fastapi.security import OAuth2PasswordRequestForm

from app.api.super_admin_deps import (
    PlatformServiceDep,
    SuperAdminAuthServiceDep,
    SuperAdminUser,
)
from app.api.v1.responses import ERROR_RESPONSES
from app.core.auth_cookies import (
    clear_auth_cookies,
    read_refresh_cookie,
    set_auth_cookies,
)
from app.core.client_ip import client_ip
from app.core.config import get_settings
from app.core.exceptions import NotFoundError, UnauthorizedError, ValidationError
from app.core.rate_limit import is_rate_limited
from app.db.enums import EmployeeStatus, PlatformRole
from app.db.models.super_admin import SuperAdmin
from app.schemas.auth import BrowserSessionResponse, RefreshRequest, TokenResponse
from app.schemas.company import CompanyResponse
from app.schemas.super_admin import (
    CompanyLimitsResponse,
    CompanySubscriptionResponse,
    CompanySubscriptionUpdate,
    CompanyUserCreate,
    InviteAcceptRequest,
    InviteDeliveryResponse,
    InvitePreviewResponse,
    PlatformAuditLogResponse,
    PlatformDashboardStats,
    PlatformSettingsResponse,
    PlatformSettingsUpdate,
    PlatformUserResponse,
    PlatformUserUpdate,
    SubscriptionHistoryResponse,
    SuperAdminCompanyCreate,
    SuperAdminCompanyDetail,
    SuperAdminCompanyProfileUpdate,
    SuperAdminCompanyUpdate,
    SuperAdminLoginRequest,
    SuperAdminResponse,
)
from app.services.refresh_session import SUBJECT_SUPER_ADMIN, RefreshSessionService

router = APIRouter(prefix="/super-admin", tags=["Super Admin"])
_refresh_sessions = RefreshSessionService()

_AUTH_RESPONSES = {
    status.HTTP_401_UNAUTHORIZED: {"description": "Missing or invalid Super Admin token"},
    status.HTTP_403_FORBIDDEN: {"description": "Super Admin role required"},
}


async def _issue_tokens(admin: SuperAdmin) -> TokenResponse:
    issued = await _refresh_sessions.issue(
        subject_type=SUBJECT_SUPER_ADMIN,
        subject_id=admin.id,
        role=PlatformRole.SUPER_ADMIN.value,
        company_id=None,
    )
    return issued.tokens


def _resolve_sa_refresh(request: Request, payload: RefreshRequest | None) -> str | None:
    if payload is not None and payload.refresh_token:
        return payload.refresh_token
    return read_refresh_cookie(request.cookies, kind="super_admin")


def _to_super_admin_response(admin: SuperAdmin) -> SuperAdminResponse:
    return SuperAdminResponse(
        id=admin.id,
        email=admin.email,
        full_name=admin.full_name,
        role=PlatformRole.SUPER_ADMIN.value,
        is_active=admin.is_active,
        created_at=admin.created_at,
        updated_at=admin.updated_at,
    )


def _enforce_super_admin_login_rate_limit(request: Request) -> None:
    settings = get_settings()
    ip = client_ip(request)
    limited = is_rate_limited(
        f"super_admin_login:ip:{ip}",
        limit=settings.login_rate_limit,
        window_seconds=settings.login_rate_window_seconds,
    )
    if limited:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many login attempts. Try again later.",
            headers={"Retry-After": str(settings.login_rate_window_seconds)},
        )


def _enforce_super_admin_refresh_rate_limit(request: Request) -> None:
    """Rate-limit Super Admin refresh by client IP before rotation."""
    settings = get_settings()
    ip = client_ip(request)
    limited = is_rate_limited(
        f"super_admin_refresh:ip:{ip}",
        limit=settings.refresh_rate_limit,
        window_seconds=settings.refresh_rate_window_seconds,
    )
    if limited:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many refresh attempts. Try again later.",
            headers={"Retry-After": str(settings.refresh_rate_window_seconds)},
        )


@router.post(
    "/auth/login",
    response_model=BrowserSessionResponse,
    summary="Super Admin login",
    description=(
        "Authenticate a platform Super Admin with email + password. "
        "Issues httpOnly Super Admin cookies (no raw tokens in JSON). "
        "Tokens have role ``super_admin`` and no ``company_id``. "
        "They cannot access tenant company APIs."
    ),
    responses={
        status.HTTP_401_UNAUTHORIZED: {"description": "Invalid credentials"},
        status.HTTP_403_FORBIDDEN: {"description": "Account disabled"},
        status.HTTP_429_TOO_MANY_REQUESTS: {"description": "Login rate limit exceeded"},
        status.HTTP_422_UNPROCESSABLE_CONTENT: ERROR_RESPONSES[
            status.HTTP_422_UNPROCESSABLE_CONTENT
        ],
    },
)
async def super_admin_login(
    request: Request,
    response: Response,
    payload: SuperAdminLoginRequest,
    auth: SuperAdminAuthServiceDep,
) -> BrowserSessionResponse:
    _enforce_super_admin_login_rate_limit(request)
    try:
        admin = await auth.authenticate(email=payload.email, password=payload.password)
    except NotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc
    except ValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(exc),
        ) from exc
    tokens = await _issue_tokens(admin)
    set_auth_cookies(response, tokens, kind="super_admin")
    return BrowserSessionResponse()


@router.post(
    "/auth/login/form",
    response_model=BrowserSessionResponse,
    include_in_schema=False,
    summary="Super Admin OAuth2 form login",
)
async def super_admin_login_form(
    request: Request,
    response: Response,
    form_data: Annotated[OAuth2PasswordRequestForm, Depends()],
    auth: SuperAdminAuthServiceDep,
) -> BrowserSessionResponse:
    """OAuth2 password form login (cookie-only; username = email)."""
    return await super_admin_login(
        request,
        response,
        SuperAdminLoginRequest(email=form_data.username, password=form_data.password),
        auth,
    )


@router.post(
    "/auth/refresh",
    response_model=None,
    summary="Refresh Super Admin tokens",
    description=(
        "Rotate Super Admin refresh session. Browser clients omit the JSON body "
        "and receive a cookie-only acknowledgement. Service clients that send "
        "``refresh_token`` in the body receive a full token pair."
    ),
    responses={
        status.HTTP_401_UNAUTHORIZED: {"description": "Invalid refresh token"},
        status.HTTP_403_FORBIDDEN: {"description": "Account disabled"},
        status.HTTP_429_TOO_MANY_REQUESTS: {"description": "Refresh rate limit exceeded"},
    },
)
async def super_admin_refresh(
    request: Request,
    response: Response,
    auth: SuperAdminAuthServiceDep,
    payload: RefreshRequest | None = None,
) -> BrowserSessionResponse | TokenResponse:
    _enforce_super_admin_refresh_rate_limit(request)
    raw = _resolve_sa_refresh(request, payload)
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
            subject_type=SUBJECT_SUPER_ADMIN,
        )
    except UnauthorizedError as exc:
        clear_auth_cookies(response, kind="super_admin")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=exc.message,
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc

    try:
        admin = await auth.get_by_id(subject_id)
    except NotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid refresh token",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc
    except ValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(exc),
        ) from exc

    issued = await _refresh_sessions.issue(
        subject_type=SUBJECT_SUPER_ADMIN,
        subject_id=admin.id,
        role=PlatformRole.SUPER_ADMIN.value,
        company_id=None,
        family_id=family_id,
    )
    set_auth_cookies(response, issued.tokens, kind="super_admin")
    if service_mode:
        return issued.tokens
    return BrowserSessionResponse()


@router.post(
    "/auth/logout",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Super Admin logout",
)
async def super_admin_logout(
    request: Request,
    response: Response,
    payload: RefreshRequest | None = None,
) -> None:
    raw = _resolve_sa_refresh(request, payload)
    await _refresh_sessions.revoke_raw(raw)
    clear_auth_cookies(response, kind="super_admin")


@router.get(
    "/auth/me",
    response_model=SuperAdminResponse,
    summary="Current Super Admin",
    responses={**_AUTH_RESPONSES},
)
async def super_admin_me(current: SuperAdminUser) -> SuperAdminResponse:
    return _to_super_admin_response(current)


@router.get(
    "/dashboard",
    response_model=PlatformDashboardStats,
    summary="Platform dashboard stats",
    responses={**_AUTH_RESPONSES},
)
async def platform_dashboard(
    _: SuperAdminUser,
    service: PlatformServiceDep,
) -> PlatformDashboardStats:
    return await service.get_dashboard_stats()


@router.get(
    "/companies",
    response_model=list[CompanyResponse],
    summary="List all companies",
    responses={**_AUTH_RESPONSES},
)
async def list_all_companies(
    _: SuperAdminUser,
    service: PlatformServiceDep,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=1000)] = 100,
    is_active: Annotated[bool | None, Query()] = None,
) -> list[CompanyResponse]:
    companies = await service.list_companies(
        offset=offset,
        limit=limit,
        is_active=is_active,
    )
    return [CompanyResponse.model_validate(c) for c in companies]


@router.get(
    "/companies/{company_id}",
    response_model=SuperAdminCompanyDetail,
    summary="Get company detail",
    responses={
        **_AUTH_RESPONSES,
        status.HTTP_404_NOT_FOUND: ERROR_RESPONSES[status.HTTP_404_NOT_FOUND],
    },
)
async def get_company_detail(
    company_id: UUID,
    _: SuperAdminUser,
    service: PlatformServiceDep,
) -> SuperAdminCompanyDetail:
    return await service.get_company(company_id)


@router.post(
    "/companies",
    response_model=SuperAdminCompanyDetail,
    status_code=status.HTTP_201_CREATED,
    summary="Create company with first admin",
    description=(
        "Create a new company tenant and provision the first "
        "company administrator (role=admin, status=invited). "
        "An invite is created; delivery is SMTP when configured, otherwise "
        "the response includes invite_url for manual sharing."
    ),
    responses={
        **_AUTH_RESPONSES,
        status.HTTP_409_CONFLICT: ERROR_RESPONSES[status.HTTP_409_CONFLICT],
    },
)
async def create_company_with_admin(
    payload: SuperAdminCompanyCreate,
    current: SuperAdminUser,
    service: PlatformServiceDep,
) -> SuperAdminCompanyDetail:
    company, _admin, delivery = await service.create_company_with_admin(
        name=payload.name,
        slug=payload.slug,
        timezone=payload.timezone,
        settings=payload.settings,
        description=payload.description,
        logo_url=payload.logo_url,
        contact_email=payload.contact_email,
        contact_phone=payload.contact_phone,
        contact_person=payload.contact_person,
        admin_full_name=payload.admin_full_name,
        admin_email=payload.admin_email,
        admin_telegram_user_id=payload.admin_telegram_user_id,
        super_admin_id=current.id,
    )
    detail = await service.get_company(company.id)
    return detail.model_copy(
        update={
            "invite_email_sent": delivery.email_sent,
            "invite_delivery": delivery.delivery,
            "invite_url": delivery.invite_url,
            "invite_detail": delivery.detail,
            "invite_telegram_url": delivery.telegram_invite_url,
        }
    )


@router.patch(
    "/companies/{company_id}/profile",
    response_model=SuperAdminCompanyDetail,
    summary="Update company profile card",
    responses={
        **_AUTH_RESPONSES,
        status.HTTP_404_NOT_FOUND: ERROR_RESPONSES[status.HTTP_404_NOT_FOUND],
    },
)
async def update_company_profile(
    company_id: UUID,
    payload: SuperAdminCompanyProfileUpdate,
    current: SuperAdminUser,
    service: PlatformServiceDep,
) -> SuperAdminCompanyDetail:
    return await service.update_company_profile(
        company_id,
        payload,
        super_admin_id=current.id,
    )


@router.patch(
    "/companies/{company_id}",
    response_model=CompanyResponse,
    summary="Update company",
    responses={
        **_AUTH_RESPONSES,
        status.HTTP_404_NOT_FOUND: ERROR_RESPONSES[status.HTTP_404_NOT_FOUND],
        status.HTTP_409_CONFLICT: ERROR_RESPONSES[status.HTTP_409_CONFLICT],
    },
)
async def update_company(
    company_id: UUID,
    payload: SuperAdminCompanyUpdate,
    _: SuperAdminUser,
    service: PlatformServiceDep,
) -> CompanyResponse:
    values = payload.model_dump(exclude_unset=True)
    company = await service.update_company(company_id, **values)
    return CompanyResponse.model_validate(company)


@router.post(
    "/companies/{company_id}/deactivate",
    response_model=CompanyResponse,
    summary="Deactivate (block) company",
    responses={
        **_AUTH_RESPONSES,
        status.HTTP_404_NOT_FOUND: ERROR_RESPONSES[status.HTTP_404_NOT_FOUND],
    },
)
async def deactivate_company(
    company_id: UUID,
    current: SuperAdminUser,
    service: PlatformServiceDep,
) -> CompanyResponse:
    company = await service.set_company_active(
        company_id,
        is_active=False,
        super_admin_id=current.id,
    )
    return CompanyResponse.model_validate(company)


@router.post(
    "/companies/{company_id}/activate",
    response_model=CompanyResponse,
    summary="Activate company",
    responses={
        **_AUTH_RESPONSES,
        status.HTTP_404_NOT_FOUND: ERROR_RESPONSES[status.HTTP_404_NOT_FOUND],
    },
)
async def activate_company(
    company_id: UUID,
    current: SuperAdminUser,
    service: PlatformServiceDep,
) -> CompanyResponse:
    company = await service.set_company_active(
        company_id,
        is_active=True,
        super_admin_id=current.id,
    )
    return CompanyResponse.model_validate(company)


@router.get(
    "/companies/{company_id}/subscription",
    response_model=CompanySubscriptionResponse,
    summary="Get current company subscription",
    responses={**_AUTH_RESPONSES},
)
async def get_company_subscription(
    company_id: UUID,
    _: SuperAdminUser,
    service: PlatformServiceDep,
) -> CompanySubscriptionResponse:
    return await service.get_subscription(company_id)


@router.patch(
    "/companies/{company_id}/subscription",
    response_model=CompanySubscriptionResponse,
    summary="Update company subscription",
    responses={**_AUTH_RESPONSES},
)
async def update_company_subscription(
    company_id: UUID,
    payload: CompanySubscriptionUpdate,
    current: SuperAdminUser,
    service: PlatformServiceDep,
) -> CompanySubscriptionResponse:
    return await service.update_subscription(
        company_id,
        payload,
        super_admin_id=current.id,
    )


@router.get(
    "/companies/{company_id}/subscription/history",
    response_model=list[SubscriptionHistoryResponse],
    summary="Subscription status history",
    responses={**_AUTH_RESPONSES},
)
async def list_subscription_history(
    company_id: UUID,
    _: SuperAdminUser,
    service: PlatformServiceDep,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=1000)] = 100,
) -> list[SubscriptionHistoryResponse]:
    return await service.list_subscription_history(company_id, offset=offset, limit=limit)


@router.get(
    "/companies/{company_id}/subscriptions",
    response_model=list[CompanySubscriptionResponse],
    summary="All subscription records",
    responses={**_AUTH_RESPONSES},
)
async def list_company_subscriptions(
    company_id: UUID,
    _: SuperAdminUser,
    service: PlatformServiceDep,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=1000)] = 100,
) -> list[CompanySubscriptionResponse]:
    return await service.list_subscriptions(company_id, offset=offset, limit=limit)


@router.get(
    "/companies/{company_id}/limits",
    response_model=CompanyLimitsResponse,
    summary="Company usage limits",
    responses={**_AUTH_RESPONSES},
)
async def get_company_limits(
    company_id: UUID,
    _: SuperAdminUser,
    service: PlatformServiceDep,
) -> CompanyLimitsResponse:
    return await service.get_company_limits(company_id)


@router.get(
    "/companies/{company_id}/users",
    response_model=list[PlatformUserResponse],
    summary="List company users",
    responses={**_AUTH_RESPONSES},
)
async def list_company_users(
    company_id: UUID,
    _: SuperAdminUser,
    service: PlatformServiceDep,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=1000)] = 100,
    role: Annotated[str | None, Query()] = None,
    status_filter: Annotated[str | None, Query(alias="status")] = None,
) -> list[PlatformUserResponse]:
    return await service.list_company_users(
        company_id,
        offset=offset,
        limit=limit,
        role=role,
        status=status_filter,
    )


@router.post(
    "/companies/{company_id}/users",
    response_model=PlatformUserResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create company user and send invite",
    responses={**_AUTH_RESPONSES},
)
async def create_company_user(
    company_id: UUID,
    payload: CompanyUserCreate,
    current: SuperAdminUser,
    service: PlatformServiceDep,
) -> PlatformUserResponse:
    return await service.create_company_user(
        company_id,
        payload,
        super_admin_id=current.id,
    )


@router.post(
    "/users/{employee_id}/resend-invite",
    response_model=InviteDeliveryResponse,
    summary="Resend user invite email",
    responses={**_AUTH_RESPONSES},
)
async def resend_user_invite(
    employee_id: UUID,
    current: SuperAdminUser,
    service: PlatformServiceDep,
) -> InviteDeliveryResponse:
    delivery = await service.resend_invite(employee_id, super_admin_id=current.id)
    return InviteDeliveryResponse(
        email_sent=delivery.email_sent,
        delivery=delivery.delivery,
        invite_url=delivery.invite_url,
        detail=delivery.detail,
        telegram_invite_url=delivery.telegram_invite_url,
    )


@router.get(
    "/users",
    response_model=list[PlatformUserResponse],
    summary="List company administrators",
    description="List company admin and HR users across all tenants.",
    responses={**_AUTH_RESPONSES},
)
async def list_platform_users(
    _: SuperAdminUser,
    service: PlatformServiceDep,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=1000)] = 100,
    company_id: Annotated[UUID | None, Query()] = None,
    role: Annotated[str | None, Query(description="admin or hr")] = None,
    status_filter: Annotated[
        str | None,
        Query(alias="status", description="invited | active | archived"),
    ] = None,
) -> list[PlatformUserResponse]:
    return await service.list_company_admins(
        offset=offset,
        limit=limit,
        company_id=company_id,
        role=role,
        status=status_filter,
    )


@router.patch(
    "/users/{employee_id}",
    response_model=PlatformUserResponse,
    summary="Update company user role/status",
    responses={
        **_AUTH_RESPONSES,
        status.HTTP_404_NOT_FOUND: ERROR_RESPONSES[status.HTTP_404_NOT_FOUND],
    },
)
async def update_platform_user(
    employee_id: UUID,
    payload: PlatformUserUpdate,
    current: SuperAdminUser,
    service: PlatformServiceDep,
) -> PlatformUserResponse:
    values = payload.model_dump(exclude_unset=True)
    return await service.update_company_user(
        employee_id,
        super_admin_id=current.id,
        **values,
    )


@router.post(
    "/users/{employee_id}/block",
    response_model=PlatformUserResponse,
    summary="Block (archive) company user",
    responses={
        **_AUTH_RESPONSES,
        status.HTTP_404_NOT_FOUND: ERROR_RESPONSES[status.HTTP_404_NOT_FOUND],
    },
)
async def block_platform_user(
    employee_id: UUID,
    current: SuperAdminUser,
    service: PlatformServiceDep,
) -> PlatformUserResponse:
    return await service.block_company_user(employee_id, super_admin_id=current.id)


@router.get(
    "/audit-logs",
    response_model=list[PlatformAuditLogResponse],
    summary="Platform audit log",
    responses={**_AUTH_RESPONSES},
)
async def list_audit_logs(
    _: SuperAdminUser,
    service: PlatformServiceDep,
    offset: Annotated[int, Query(ge=0)] = 0,
    limit: Annotated[int, Query(ge=1, le=1000)] = 100,
    company_id: Annotated[UUID | None, Query()] = None,
) -> list[PlatformAuditLogResponse]:
    return await service.list_audit_logs(
        offset=offset,
        limit=limit,
        company_id=company_id,
    )


@router.get(
    "/settings",
    response_model=PlatformSettingsResponse,
    summary="Global platform settings (stub)",
    responses={**_AUTH_RESPONSES},
)
async def get_platform_settings(
    _: SuperAdminUser,
    service: PlatformServiceDep,
) -> PlatformSettingsResponse:
    return service.get_settings()


@router.patch(
    "/settings",
    response_model=PlatformSettingsResponse,
    summary="Update platform settings (stub)",
    description="In-memory stub — not persisted across restarts.",
    responses={**_AUTH_RESPONSES},
)
async def update_platform_settings(
    payload: PlatformSettingsUpdate,
    current: SuperAdminUser,
    service: PlatformServiceDep,
) -> PlatformSettingsResponse:
    return service.update_settings(payload, super_admin_id=current.id)

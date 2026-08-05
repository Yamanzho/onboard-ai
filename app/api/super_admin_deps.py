from collections.abc import Callable
from typing import Annotated
from uuid import UUID

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer

from app.api.deps import get_platform_service, get_super_admin_auth_service
from app.core.exceptions import NotFoundError, ValidationError
from app.core.security import InvalidTokenError, decode_token
from app.db.enums import PlatformRole
from app.db.models.super_admin import SuperAdmin
from app.services.platform import PlatformService, SuperAdminAuthService

super_admin_oauth2_scheme = OAuth2PasswordBearer(
    tokenUrl="/api/v1/super-admin/auth/login/form",
)

SuperAdminAuthServiceDep = Annotated[
    SuperAdminAuthService,
    Depends(get_super_admin_auth_service),
]
PlatformServiceDep = Annotated[PlatformService, Depends(get_platform_service)]


async def get_current_super_admin(
    token: Annotated[str, Depends(super_admin_oauth2_scheme)],
    auth: SuperAdminAuthServiceDep,
) -> SuperAdmin:
    """Resolve the authenticated platform Super Admin from a Bearer token."""
    try:
        payload = decode_token(token, expected_type="access")
        if payload.get("role") != PlatformRole.SUPER_ADMIN.value:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Could not validate credentials",
                headers={"WWW-Authenticate": "Bearer"},
            )
        admin_id = UUID(payload["sub"])
    except (InvalidTokenError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc

    try:
        return await auth.get_by_id(admin_id)
    except NotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc
    except ValidationError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=str(exc),
        ) from exc


SuperAdminUser = Annotated[SuperAdmin, Depends(get_current_super_admin)]


def require_super_admin() -> Callable[..., SuperAdmin]:
    """Explicit Super Admin guard (alias for documentation clarity)."""
    return get_current_super_admin

from collections.abc import Callable
from typing import Annotated
from uuid import UUID

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer

from app.api.deps import get_employee_service
from app.core.auth_cookies import read_access_cookie
from app.core.exceptions import ForbiddenError, NotFoundError
from app.core.security import InvalidTokenError, decode_token
from app.db.enums import EmployeeRole, EmployeeStatus, PlatformRole
from app.db.models.assignment import Assignment
from app.db.models.employee import Employee
from app.services.employee import EmployeeService

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login", auto_error=False)

EmployeeServiceDep = Annotated[EmployeeService, Depends(get_employee_service)]

_HR_OR_ADMIN = frozenset({EmployeeRole.ADMIN.value, EmployeeRole.HR.value})


def _extract_access_token(request: Request, bearer: str | None) -> str | None:
    if bearer:
        return bearer
    return read_access_cookie(request.cookies, kind="tenant")


async def get_current_user(
    request: Request,
    token: Annotated[str | None, Depends(oauth2_scheme)],
    employees: EmployeeServiceDep,
) -> Employee:
    """Resolve the authenticated employee from Bearer or httpOnly access cookie.

    Platform Super Admin tokens are rejected here — they use
    ``/api/v1/super-admin/*`` endpoints exclusively.
    """
    access = _extract_access_token(request, token)
    if not access:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        payload = decode_token(access, expected_type="access")
        if payload.get("role") == PlatformRole.SUPER_ADMIN.value:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Could not validate credentials",
                headers={"WWW-Authenticate": "Bearer"},
            )
        employee_id = UUID(payload["sub"])
    except (InvalidTokenError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
            headers={"WWW-Authenticate": "Bearer"},
        ) from exc

    try:
        employee = await employees.get_employee(employee_id)
    except NotFoundError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Could not validate credentials",
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


def require_roles(*allowed_roles: str) -> Callable[..., Employee]:
    """Factory for role-guard dependencies."""

    allowed = set(allowed_roles)

    async def _dependency(
        current_user: Annotated[Employee, Depends(get_current_user)],
    ) -> Employee:
        if current_user.role not in allowed:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Insufficient permissions",
            )
        return current_user

    return _dependency


def assert_can_view_assignment_progress(user: Employee, assignment: Assignment) -> None:
    """HR/admin may view any assignment progress; employees only their own."""
    if user.role in _HR_OR_ADMIN:
        return
    if user.id != assignment.employee_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Insufficient permissions",
        )


def assert_can_list_employee_assignments(user: Employee, employee_id: UUID) -> None:
    """HR/admin may list any employee assignments; employees only their own."""
    if user.role in _HR_OR_ADMIN:
        return
    if user.id != employee_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Insufficient permissions",
        )


def assert_can_complete_assignment_progress(user: Employee, assignment: Assignment) -> None:
    """Only the assigned employee may complete their own progress steps."""
    if user.id != assignment.employee_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Insufficient permissions",
        )


require_admin = require_roles(EmployeeRole.ADMIN.value)
require_hr = require_roles(EmployeeRole.ADMIN.value, EmployeeRole.HR.value)
require_employee = require_roles(
    EmployeeRole.ADMIN.value,
    EmployeeRole.HR.value,
    EmployeeRole.EMPLOYEE.value,
)

CurrentUser = Annotated[Employee, Depends(get_current_user)]
AdminUser = Annotated[Employee, Depends(require_admin)]
HRUser = Annotated[Employee, Depends(require_hr)]
EmployeeUser = Annotated[Employee, Depends(require_employee)]

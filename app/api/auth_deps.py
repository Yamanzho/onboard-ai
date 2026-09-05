from collections.abc import Callable
from typing import Annotated
from uuid import UUID

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer

from app.api.deps import get_employee_service
from app.core import capabilities as capability_catalog
from app.core.auth_cookies import read_access_cookie
from app.core.capabilities import (
    Capability,
    ScopeDeniedError,
    VisibilityScope,
)
from app.core.exceptions import ForbiddenError, NotFoundError
from app.core.security import InvalidTokenError, decode_token
from app.db.enums import EmployeeRole, EmployeeStatus, PlatformRole
from app.db.models.assignment import Assignment
from app.db.models.employee import Employee
from app.services.employee import EmployeeService

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/login", auto_error=False)

EmployeeServiceDep = Annotated[EmployeeService, Depends(get_employee_service)]


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
    """Factory for role-guard dependencies (legacy / platform-adjacent)."""

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


def require_capability(*needed: str) -> Callable[..., Employee]:
    """Require every listed capability (server-resolved from role)."""

    required = frozenset(needed)

    async def _dependency(
        current_user: Annotated[Employee, Depends(get_current_user)],
    ) -> Employee:
        caps = capability_catalog.capabilities_for_employee(current_user)
        if not required.issubset(caps):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Insufficient permissions",
            )
        return current_user

    return _dependency


def require_any_capability(*needed: str) -> Callable[..., Employee]:
    """Require at least one of the listed capabilities."""

    allowed = frozenset(needed)

    async def _dependency(
        current_user: Annotated[Employee, Depends(get_current_user)],
    ) -> Employee:
        caps = capability_catalog.capabilities_for_employee(current_user)
        if caps.isdisjoint(allowed):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Insufficient permissions",
            )
        return current_user

    return _dependency


def _forbidden() -> None:
    raise HTTPException(
        status_code=status.HTTP_403_FORBIDDEN,
        detail="Insufficient permissions",
    )


def assert_assignment_visible(
    user: Employee,
    assignment: Assignment,
    *,
    assignee_department_id: UUID | None,
    scope: VisibilityScope | None = None,
) -> None:
    if capability_catalog.assignment_in_scope(
        user,
        assignment_employee_id=assignment.employee_id,
        assignee_department_id=assignee_department_id,
        assignee_company_id=assignment.company_id,
        scope=scope,
    ):
        return
    _forbidden()


async def assert_can_view_assignment_progress(
    user: Employee,
    assignment: Assignment,
    employees: EmployeeService,
) -> None:
    """Progress visibility: own / department / all. Strongest scope wins."""
    scope = capability_catalog.progress_visibility_scope(user)
    if scope is VisibilityScope.NONE:
        _forbidden()
    if scope is VisibilityScope.ALL:
        return
    if assignment.employee_id == user.id:
        return
    if scope is VisibilityScope.OWN:
        _forbidden()
    assignee = await employees.get_employee(
        assignment.employee_id,
        company_id=user.company_id,
    )
    if capability_catalog.assignment_in_scope(
        user,
        assignment_employee_id=assignment.employee_id,
        assignee_department_id=assignee.department_id,
        assignee_company_id=assignee.company_id,
        scope=scope,
    ):
        return
    _forbidden()


async def assert_can_view_assignment(
    user: Employee,
    assignment: Assignment,
    employees: EmployeeService,
) -> None:
    scope = capability_catalog.assignment_visibility_scope(user)
    if scope is VisibilityScope.NONE:
        _forbidden()
    if scope is VisibilityScope.ALL:
        return
    if assignment.employee_id == user.id:
        return
    if scope is VisibilityScope.OWN:
        _forbidden()
    assignee = await employees.get_employee(
        assignment.employee_id,
        company_id=user.company_id,
    )
    assert_assignment_visible(
        user,
        assignment,
        assignee_department_id=assignee.department_id,
        scope=scope,
    )


async def assert_can_list_employee_assignments(
    user: Employee,
    employee_id: UUID,
    employees: EmployeeService,
) -> None:
    scope = capability_catalog.assignment_visibility_scope(user)
    if scope is VisibilityScope.NONE:
        _forbidden()
    if scope is VisibilityScope.ALL:
        return
    if user.id == employee_id:
        return
    if scope is VisibilityScope.OWN:
        _forbidden()
    target = await employees.get_employee(employee_id, company_id=user.company_id)
    if not capability_catalog.employee_in_scope(user, target, scope):
        _forbidden()


async def assert_can_manage_assignment(
    user: Employee,
    assignment: Assignment,
    employees: EmployeeService,
) -> None:
    if not capability_catalog.has_capability(user, Capability.ASSIGNMENTS_MANAGE):
        _forbidden()
    await assert_can_view_assignment(user, assignment, employees)


async def assert_targets_in_assignment_scope(
    user: Employee,
    *,
    employee_ids: list[UUID],
    department_ids: list[UUID],
    employees: EmployeeService,
) -> None:
    """Reject create/assign targets outside the caller's assignment scope."""
    scope = capability_catalog.assignment_visibility_scope(user)
    if not capability_catalog.has_capability(user, Capability.ASSIGNMENTS_MANAGE):
        _forbidden()
    if scope is VisibilityScope.ALL:
        return
    if scope is not VisibilityScope.DEPARTMENT:
        _forbidden()
    try:
        allowed_dept = capability_catalog.scoped_department_id(user, scope)
    except ScopeDeniedError:
        _forbidden()
        return
    if allowed_dept is None:
        _forbidden()
    for department_id in department_ids:
        if department_id != allowed_dept:
            _forbidden()
    for employee_id in employee_ids:
        target = await employees.get_employee(
            employee_id,
            company_id=user.company_id,
        )
        if not capability_catalog.employee_in_scope(user, target, scope):
            _forbidden()


def resolve_list_department_id(
    user: Employee,
    requested: UUID | None,
    *,
    family: str = "assignment",
) -> UUID | None:
    """Department filter for list/analytics. Raises 403 if requested id is outside scope."""
    if family == "progress":
        scope = capability_catalog.progress_visibility_scope(user)
    elif family == "analytics":
        scope = capability_catalog.analytics_visibility_scope(user)
    else:
        scope = capability_catalog.assignment_visibility_scope(user)
    try:
        return capability_catalog.scoped_department_id(user, scope, requested)
    except ScopeDeniedError as exc:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Insufficient permissions",
        ) from exc


def assert_can_complete_assignment_progress(user: Employee, assignment: Assignment) -> None:
    """Only the assigned employee may complete their own progress steps."""
    if user.id != assignment.employee_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Insufficient permissions",
        )


def assert_can_mutate_own_assignment_reminders(user: Employee, assignment: Assignment) -> None:
    """Only the assigned employee may change reminder preference."""
    if user.id != assignment.employee_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Insufficient permissions",
        )


def redact_progress_for_viewer(user: Employee) -> bool:
    """Hide quiz/step internals unless the viewer has management progress scope."""
    scope = capability_catalog.progress_visibility_scope(user)
    return scope in {VisibilityScope.OWN, VisibilityScope.NONE}


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

EmployeesViewUser = Annotated[
    Employee, Depends(require_capability(Capability.EMPLOYEES_VIEW))
]
EmployeesManageUser = Annotated[
    Employee, Depends(require_capability(Capability.EMPLOYEES_MANAGE))
]
DepartmentsViewUser = Annotated[
    Employee, Depends(require_capability(Capability.DEPARTMENTS_VIEW))
]
DepartmentsManageUser = Annotated[
    Employee, Depends(require_capability(Capability.DEPARTMENTS_MANAGE))
]
CoursesViewUser = Annotated[
    Employee, Depends(require_capability(Capability.COURSES_VIEW))
]
CoursesCreateUser = Annotated[
    Employee, Depends(require_capability(Capability.COURSES_CREATE))
]
CoursesEditUser = Annotated[
    Employee, Depends(require_capability(Capability.COURSES_EDIT))
]
AssignmentsManageUser = Annotated[
    Employee, Depends(require_capability(Capability.ASSIGNMENTS_MANAGE))
]
AssignmentsReadUser = Annotated[
    Employee,
    Depends(
        require_any_capability(
            Capability.ASSIGNMENTS_VIEW_ALL,
            Capability.ASSIGNMENTS_VIEW_DEPARTMENT,
        )
    ),
]
KnowledgeManageUser = Annotated[
    Employee, Depends(require_capability(Capability.KNOWLEDGE_MANAGE))
]
ResponsibilitiesViewUser = Annotated[
    Employee, Depends(require_capability(Capability.RESPONSIBILITIES_VIEW))
]
ResponsibilitiesManageUser = Annotated[
    Employee, Depends(require_capability(Capability.RESPONSIBILITIES_MANAGE))
]
AnalyticsViewUser = Annotated[
    Employee, Depends(require_capability(Capability.ANALYTICS_VIEW))
]
CompanySettingsUser = Annotated[
    Employee, Depends(require_capability(Capability.COMPANY_SETTINGS_MANAGE))
]

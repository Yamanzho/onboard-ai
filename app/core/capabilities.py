"""Application-level capability authorization.

Roles remain presets. Capabilities are the API/UI check primitive.
RLS stays tenant isolation / employee ownership — never encode capabilities there.

Effective capabilities are resolved server-side from the employee's role.
No permission tables and no JWT capability claims.
"""

from __future__ import annotations

from enum import StrEnum
from uuid import UUID

from app.db.enums import EmployeeRole
from app.db.models.employee import Employee


class Capability(StrEnum):
    EMPLOYEES_VIEW = "employees.view"
    EMPLOYEES_MANAGE = "employees.manage"

    DEPARTMENTS_VIEW = "departments.view"
    DEPARTMENTS_MANAGE = "departments.manage"

    COURSES_VIEW = "courses.view"
    COURSES_CREATE = "courses.create"
    COURSES_EDIT = "courses.edit"
    COURSES_ASSIGN = "courses.assign"

    ASSIGNMENTS_VIEW_ALL = "assignments.view_all"
    ASSIGNMENTS_VIEW_DEPARTMENT = "assignments.view_department"
    ASSIGNMENTS_VIEW_OWN = "assignments.view_own"
    ASSIGNMENTS_MANAGE = "assignments.manage"

    DEADLINES_MANAGE = "deadlines.manage"

    PROGRESS_VIEW_ALL = "progress.view_all"
    PROGRESS_VIEW_DEPARTMENT = "progress.view_department"
    PROGRESS_VIEW_OWN = "progress.view_own"

    KNOWLEDGE_VIEW = "knowledge.view"
    KNOWLEDGE_MANAGE = "knowledge.manage"

    RESPONSIBILITIES_VIEW = "responsibilities.view"
    RESPONSIBILITIES_MANAGE = "responsibilities.manage"

    ANALYTICS_VIEW = "analytics.view"

    COMPANY_SETTINGS_MANAGE = "company.settings.manage"


class VisibilityScope(StrEnum):
    """Strongest allowed visibility for assignment/progress/analytics families."""

    NONE = "none"
    OWN = "own"
    DEPARTMENT = "department"
    ALL = "all"


# Company-level capabilities (never includes platform Super Admin).
ALL_COMPANY_CAPABILITIES: frozenset[str] = frozenset(item.value for item in Capability)

_ADMIN_CAPABILITIES: frozenset[str] = ALL_COMPANY_CAPABILITIES

_HR_CAPABILITIES: frozenset[str] = frozenset(
    {
        Capability.EMPLOYEES_VIEW,
        Capability.EMPLOYEES_MANAGE,
        Capability.DEPARTMENTS_VIEW,
        Capability.DEPARTMENTS_MANAGE,
        Capability.COURSES_VIEW,
        Capability.COURSES_CREATE,
        Capability.COURSES_EDIT,
        Capability.COURSES_ASSIGN,
        Capability.ASSIGNMENTS_VIEW_ALL,
        Capability.ASSIGNMENTS_MANAGE,
        Capability.DEADLINES_MANAGE,
        Capability.PROGRESS_VIEW_ALL,
        Capability.KNOWLEDGE_VIEW,
        Capability.KNOWLEDGE_MANAGE,
        Capability.RESPONSIBILITIES_VIEW,
        Capability.RESPONSIBILITIES_MANAGE,
        Capability.ANALYTICS_VIEW,
    }
)

_EMPLOYEE_CAPABILITIES: frozenset[str] = frozenset(
    {
        Capability.ASSIGNMENTS_VIEW_OWN,
        Capability.PROGRESS_VIEW_OWN,
        Capability.KNOWLEDGE_VIEW,
    }
)

ROLE_CAPABILITIES: dict[str, frozenset[str]] = {
    EmployeeRole.ADMIN.value: _ADMIN_CAPABILITIES,
    EmployeeRole.HR.value: _HR_CAPABILITIES,
    EmployeeRole.EMPLOYEE.value: _EMPLOYEE_CAPABILITIES,
}


def capabilities_for_role(role: str) -> frozenset[str]:
    """Default capability set for a tenant role. Unknown roles get nothing."""
    return ROLE_CAPABILITIES.get(role, frozenset())


def capabilities_for_employee(employee: Employee) -> frozenset[str]:
    """Effective capabilities. Patch point for department-scope tests."""
    return capabilities_for_role(employee.role)


def has_capability(employee: Employee, capability: str) -> bool:
    return capability in capabilities_for_employee(employee)


def visibility_scope(
    capabilities: frozenset[str],
    *,
    all_cap: str,
    department_cap: str,
    own_cap: str,
) -> VisibilityScope:
    """Strongest matching scope wins."""
    if all_cap in capabilities:
        return VisibilityScope.ALL
    if department_cap in capabilities:
        return VisibilityScope.DEPARTMENT
    if own_cap in capabilities:
        return VisibilityScope.OWN
    return VisibilityScope.NONE


def assignment_visibility_scope(employee: Employee) -> VisibilityScope:
    return visibility_scope(
        capabilities_for_employee(employee),
        all_cap=Capability.ASSIGNMENTS_VIEW_ALL,
        department_cap=Capability.ASSIGNMENTS_VIEW_DEPARTMENT,
        own_cap=Capability.ASSIGNMENTS_VIEW_OWN,
    )


def progress_visibility_scope(employee: Employee) -> VisibilityScope:
    return visibility_scope(
        capabilities_for_employee(employee),
        all_cap=Capability.PROGRESS_VIEW_ALL,
        department_cap=Capability.PROGRESS_VIEW_DEPARTMENT,
        own_cap=Capability.PROGRESS_VIEW_OWN,
    )


def analytics_visibility_scope(employee: Employee) -> VisibilityScope:
    """Analytics uses the progress visibility family so aggregates cannot leak."""
    if not has_capability(employee, Capability.ANALYTICS_VIEW):
        return VisibilityScope.NONE
    return progress_visibility_scope(employee)


def scoped_department_id(
    employee: Employee,
    scope: VisibilityScope,
    requested: UUID | None = None,
) -> UUID | None:
    """Resolve the department filter the caller is allowed to apply.

    ALL: optional requested department.
    DEPARTMENT: always the actor's department (requested ids outside it rejected).
    OWN/NONE: no department filter (caller must forbid analytics/list separately).
    """
    if scope is VisibilityScope.ALL:
        return requested
    if scope is VisibilityScope.DEPARTMENT:
        if requested is not None and requested != employee.department_id:
            raise ScopeDeniedError("Department is outside the allowed visibility scope")
        return employee.department_id
    if requested is not None:
        raise ScopeDeniedError("Department is outside the allowed visibility scope")
    return None


def employee_in_scope(
    actor: Employee,
    target: Employee,
    scope: VisibilityScope,
) -> bool:
    if scope is VisibilityScope.ALL:
        return target.company_id == actor.company_id
    if target.id == actor.id and scope in {
        VisibilityScope.OWN,
        VisibilityScope.DEPARTMENT,
    }:
        return True
    if scope is VisibilityScope.DEPARTMENT:
        return (
            actor.department_id is not None
            and target.department_id == actor.department_id
            and target.company_id == actor.company_id
        )
    return False


def assignment_in_scope(
    actor: Employee,
    *,
    assignment_employee_id: UUID,
    assignee_department_id: UUID | None,
    assignee_company_id: UUID | None = None,
    scope: VisibilityScope | None = None,
) -> bool:
    resolved = scope if scope is not None else assignment_visibility_scope(actor)
    if resolved is VisibilityScope.ALL:
        if assignee_company_id is not None and assignee_company_id != actor.company_id:
            return False
        return True
    if assignment_employee_id == actor.id and resolved in {
        VisibilityScope.OWN,
        VisibilityScope.DEPARTMENT,
    }:
        return True
    if resolved is VisibilityScope.DEPARTMENT:
        return (
            actor.department_id is not None
            and assignee_department_id == actor.department_id
        )
    return False


class ScopeDeniedError(Exception):
    """Caller asked for a department/employee outside the allowed scope."""


def sorted_capability_values(employee: Employee) -> list[str]:
    return sorted(capabilities_for_employee(employee))

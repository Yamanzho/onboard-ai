"""Default role → capability mapping (no permission tables)."""

from app.core.capabilities import (
    ALL_COMPANY_CAPABILITIES,
    Capability,
    capabilities_for_role,
)
from app.db.enums import EmployeeRole


def test_admin_has_all_company_capabilities() -> None:
    caps = capabilities_for_role(EmployeeRole.ADMIN.value)
    assert caps == ALL_COMPANY_CAPABILITIES
    assert Capability.COMPANY_SETTINGS_MANAGE in caps
    assert Capability.ANALYTICS_VIEW in caps
    assert Capability.ASSIGNMENTS_VIEW_ALL in caps
    assert Capability.PROGRESS_VIEW_ALL in caps


def test_hr_has_operational_capabilities_not_company_settings() -> None:
    caps = capabilities_for_role(EmployeeRole.HR.value)
    assert Capability.EMPLOYEES_MANAGE in caps
    assert Capability.COURSES_CREATE in caps
    assert Capability.COURSES_EDIT in caps
    assert Capability.COURSES_ASSIGN in caps
    assert Capability.ASSIGNMENTS_MANAGE in caps
    assert Capability.ASSIGNMENTS_VIEW_ALL in caps
    assert Capability.PROGRESS_VIEW_ALL in caps
    assert Capability.KNOWLEDGE_MANAGE in caps
    assert Capability.RESPONSIBILITIES_MANAGE in caps
    assert Capability.ANALYTICS_VIEW in caps
    assert Capability.COMPANY_SETTINGS_MANAGE not in caps
    assert Capability.ASSIGNMENTS_VIEW_OWN not in caps


def test_employee_own_only_capabilities() -> None:
    caps = capabilities_for_role(EmployeeRole.EMPLOYEE.value)
    assert caps == frozenset(
        {
            Capability.ASSIGNMENTS_VIEW_OWN,
            Capability.PROGRESS_VIEW_OWN,
            Capability.KNOWLEDGE_VIEW,
        }
    )
    assert Capability.ASSIGNMENTS_MANAGE not in caps
    assert Capability.COURSES_EDIT not in caps
    assert Capability.ANALYTICS_VIEW not in caps
    assert Capability.EMPLOYEES_VIEW not in caps
    assert Capability.COMPANY_SETTINGS_MANAGE not in caps


def test_no_platform_capability_on_tenant_roles() -> None:
    for role in (
        EmployeeRole.ADMIN.value,
        EmployeeRole.HR.value,
        EmployeeRole.EMPLOYEE.value,
    ):
        caps = capabilities_for_role(role)
        assert not any("platform" in item or "super_admin" in item for item in caps)


def test_unknown_role_has_no_capabilities() -> None:
    assert capabilities_for_role("super_admin") == frozenset()
    assert capabilities_for_role("unknown") == frozenset()

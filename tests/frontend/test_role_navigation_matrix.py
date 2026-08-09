"""Frontend navigation / role / workspace matrix (no DOM).

Mirrors frontend/src/lib/navigation.ts + workspace.ts for regression checks.
"""

from __future__ import annotations

ROLE_WORKSPACE = {
    "super_admin": "platform",
    "admin": "company",
    "hr": "hr",
    "employee": "employee",
}

WORKSPACE_BASE = {
    "platform": "/platform",
    "company": "/company",
    "hr": "/hr",
    "employee": "/employee",
}

COMPANY_NAV = [
    "/company",
    "/company/employees",
    "/company/hr",
    "/company/onboarding",
    "/company/assignments",
    "/company/knowledge",
    "/company/progress",
    "/company/settings",
    "/company/profile",
    "/company/security",
]

HR_NAV = [
    "/hr",
    "/hr/employees",
    "/hr/onboarding",
    "/hr/assignments",
    "/hr/knowledge",
    "/hr/progress",
    "/hr/profile",
    "/hr/security",
]

EMPLOYEE_NAV = [
    "/employee",
    "/employee/onboarding",
    "/employee/active",
    "/employee/history",
    "/employee/calendar",
    "/employee/company",
    "/employee/profile",
    "/employee/security",
]

PLATFORM_NAV = [
    "/platform",
    "/platform/companies",
    "/platform/users",
    "/platform/subscriptions",
    "/platform/audit",
    "/platform/settings",
]

NAV_BY_ROLE = {
    "admin": COMPANY_NAV,
    "hr": HR_NAV,
    "employee": EMPLOYEE_NAV,
    "super_admin": PLATFORM_NAV,
}


def home_for(role: str) -> str:
    ws = ROLE_WORKSPACE[role]
    return WORKSPACE_BASE[ws]


def nav_for(role: str) -> list[str]:
    return list(NAV_BY_ROLE[role])


def workspace_allows(role: str, path: str) -> bool:
    """Whether role may open path prefix (workspace guard matrix)."""
    ws = ROLE_WORKSPACE[role]
    base = WORKSPACE_BASE[ws]
    if path == base or path.startswith(base + "/"):
        return True
    return False


def test_workspace_mapping() -> None:
    assert ROLE_WORKSPACE["super_admin"] == "platform"
    assert ROLE_WORKSPACE["admin"] == "company"
    assert ROLE_WORKSPACE["hr"] == "hr"
    assert ROLE_WORKSPACE["employee"] == "employee"


def test_home_paths() -> None:
    assert home_for("super_admin") == "/platform"
    assert home_for("admin") == "/company"
    assert home_for("hr") == "/hr"
    assert home_for("employee") == "/employee"


def test_admin_company_allowed() -> None:
    paths = nav_for("admin")
    assert "/company" in paths
    assert "/company/hr" in paths
    assert "/company/settings" in paths
    assert "/hr" not in paths
    assert "/employee" not in paths
    assert "/platform" not in paths
    assert workspace_allows("admin", "/company")
    assert workspace_allows("admin", "/company/hr")
    assert workspace_allows("admin", "/company/settings")
    assert not workspace_allows("admin", "/hr")
    assert not workspace_allows("admin", "/platform")


def test_hr_workspace_allowed() -> None:
    paths = nav_for("hr")
    assert "/hr" in paths
    assert "/hr/employees" in paths
    assert "/company" not in paths
    assert "/company/hr" not in paths
    assert "/company/settings" not in paths
    assert workspace_allows("hr", "/hr")
    assert workspace_allows("hr", "/hr/employees")
    assert not workspace_allows("hr", "/company")
    assert not workspace_allows("hr", "/company/hr")
    assert not workspace_allows("hr", "/company/settings")


def test_employee_workspace_allowed() -> None:
    paths = nav_for("employee")
    assert "/employee" in paths
    assert "/employee/onboarding" in paths
    assert "/employee/active" in paths
    assert workspace_allows("employee", "/employee")
    assert not workspace_allows("employee", "/company")
    assert not workspace_allows("employee", "/hr")
    assert not workspace_allows("employee", "/platform")
    assert "/company" not in paths
    assert "/hr" not in paths


def test_super_admin_platform_isolated() -> None:
    paths = nav_for("super_admin")
    assert "/platform" in paths
    assert "/platform/subscriptions" in paths
    assert "/platform/audit" in paths
    assert workspace_allows("super_admin", "/platform")
    assert not workspace_allows("super_admin", "/company")
    assert not workspace_allows("super_admin", "/hr")
    assert not workspace_allows("super_admin", "/employee")
    assert "/company" not in paths
    assert "/hr" not in paths
    assert "/employees" not in paths


def test_hr_hides_privileged_company_nav() -> None:
    paths = nav_for("hr")
    assert "/company/settings" not in paths
    assert "/company/hr" not in paths
    assert not any(p.startswith("/platform") for p in paths)


def test_admin_sees_hr_management_not_employee_cabinet() -> None:
    paths = nav_for("admin")
    assert "/company/hr" in paths
    assert "/employee/onboarding" not in paths

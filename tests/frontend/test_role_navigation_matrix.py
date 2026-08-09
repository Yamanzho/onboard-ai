"""Frontend navigation / role guard pure helpers (no DOM)."""

from __future__ import annotations

# Mirrors frontend/src/lib/navigation.ts + roles.ts for regression checks.


TENANT_NAV = [
    {"path": "/dashboard", "roles": {"admin"}},
    {"path": "/dashboard", "roles": {"hr"}},
    {"path": "/my-onboarding", "roles": {"employee"}},
    {"path": "/my/active", "roles": {"employee"}},
    {"path": "/employees", "roles": {"admin", "hr"}},
    {"path": "/company-settings", "roles": {"admin"}},
    {"path": "/profile", "roles": {"admin", "hr", "employee"}},
    {"path": "/security", "roles": {"admin", "hr", "employee"}},
]

SUPER_ADMIN_NAV = [
    {"path": "/super-admin/dashboard", "roles": {"super_admin"}},
    {"path": "/super-admin/subscriptions", "roles": {"super_admin"}},
]


def nav_for(role: str) -> list[str]:
    items = SUPER_ADMIN_NAV if role == "super_admin" else TENANT_NAV
    return [i["path"] for i in items if role in i["roles"]]


def test_admin_sees_company_settings_not_employee_routes() -> None:
    paths = nav_for("admin")
    assert "/company-settings" in paths
    assert "/employees" in paths
    assert "/my-onboarding" not in paths
    assert "/super-admin/dashboard" not in paths


def test_hr_hides_company_settings() -> None:
    paths = nav_for("hr")
    assert "/employees" in paths
    assert "/company-settings" not in paths
    assert "/my-onboarding" not in paths


def test_employee_only_self_service_nav() -> None:
    paths = nav_for("employee")
    assert "/my-onboarding" in paths
    assert "/my/active" in paths
    assert "/profile" in paths
    assert "/employees" not in paths
    assert "/company-settings" not in paths
    assert "/dashboard" not in paths


def test_super_admin_panel_isolated() -> None:
    paths = nav_for("super_admin")
    assert "/super-admin/dashboard" in paths
    assert "/super-admin/subscriptions" in paths
    assert "/employees" not in paths

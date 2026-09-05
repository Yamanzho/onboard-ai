"""Frontend capability/navigation matrix (mirrors lib/navigation + capabilities)."""

from __future__ import annotations

ADMIN_CAPS = {
    "employees.view",
    "employees.manage",
    "departments.view",
    "departments.manage",
    "courses.view",
    "courses.create",
    "courses.edit",
    "courses.assign",
    "assignments.view_all",
    "assignments.manage",
    "progress.view_all",
    "knowledge.view",
    "knowledge.manage",
    "responsibilities.view",
    "responsibilities.manage",
    "analytics.view",
    "company.settings.manage",
}

HR_CAPS = ADMIN_CAPS - {"company.settings.manage"}

EMPLOYEE_CAPS = {
    "assignments.view_own",
    "progress.view_own",
    "knowledge.view",
}

COMPANY_ITEMS = {
    "/company/employees": {"employees.view"},
    "/company/departments": {"departments.view"},
    "/company/topics": {"responsibilities.view"},
    "/company/onboarding": {"courses.view"},
    "/company/assignments": {"assignments.view_all", "assignments.view_department"},
    "/company/knowledge": {"knowledge.manage", "knowledge.view"},
    "/company/progress": {"progress.view_all", "progress.view_department"},
    "/company/analytics": {"analytics.view"},
    "/company/settings": {"company.settings.manage"},
}

HR_ITEMS = {
    "/hr/employees": {"employees.view"},
    "/hr/departments": {"departments.view"},
    "/hr/topics": {"responsibilities.view"},
    "/hr/onboarding": {"courses.view"},
    "/hr/assignments": {"assignments.view_all", "assignments.view_department"},
    "/hr/knowledge": {"knowledge.manage", "knowledge.view"},
    "/hr/progress": {"progress.view_all", "progress.view_department"},
    "/hr/analytics": {"analytics.view"},
}

EMPLOYEE_ITEMS = {
    "/employee": set(),
    "/employee/onboarding": set(),
    "/employee/active": set(),
    "/employee/history": set(),
    "/employee/calendar": set(),
    "/employee/company": set(),
    "/employee/knowledge": {"knowledge.view"},
    "/employee/profile": set(),
    "/employee/security": set(),
}


def _visible(required: set[str], caps: set[str]) -> bool:
    if not required:
        return True
    return bool(required & caps)


def test_admin_menu_reflects_full_company_capabilities() -> None:
    visible = [path for path, needed in COMPANY_ITEMS.items() if _visible(needed, ADMIN_CAPS)]
    assert "/company/settings" in visible
    assert "/company/analytics" in visible
    assert "/company/assignments" in visible


def test_hr_menu_hides_company_settings() -> None:
    visible = [path for path, needed in COMPANY_ITEMS.items() if _visible(needed, HR_CAPS)]
    assert "/company/settings" not in visible
    hr_visible = [path for path, needed in HR_ITEMS.items() if _visible(needed, HR_CAPS)]
    assert "/hr/analytics" in hr_visible
    assert "/hr/assignments" in hr_visible
    assert "/hr/employees" in hr_visible


def test_employee_menu_hides_management_and_web_ai() -> None:
    emp_visible = [
        path for path, needed in EMPLOYEE_ITEMS.items() if _visible(needed, EMPLOYEE_CAPS)
    ]
    assert "/employee" in emp_visible
    assert "/employee/onboarding" in emp_visible
    assert "/employee/knowledge" in emp_visible
    assert "/employee/ai" not in emp_visible
    assert "/employee/ai" not in EMPLOYEE_ITEMS
    for path in COMPANY_ITEMS:
        assert path not in emp_visible
    for path in HR_ITEMS:
        assert path not in emp_visible


def test_management_actions_hidden_without_capability() -> None:
    assert not _visible({"assignments.manage"}, EMPLOYEE_CAPS)
    assert not _visible({"courses.edit"}, EMPLOYEE_CAPS)
    assert not _visible({"employees.manage"}, EMPLOYEE_CAPS)
    assert not _visible({"analytics.view"}, EMPLOYEE_CAPS)
    assert _visible({"assignments.manage"}, HR_CAPS)
    assert _visible({"courses.edit"}, ADMIN_CAPS)


def test_assignment_type_and_analytics_labels() -> None:
    from pathlib import Path

    catalog = Path("frontend/src/i18n/ru.ts").read_text(encoding="utf-8")
    assert "assignmentType" in catalog
    assert "acknowledgement" in catalog
    assert "completionRate" in catalog
    assert "analytics:" in catalog
    assert "ознакомлен" in catalog.lower() or "Ознакомление" in catalog

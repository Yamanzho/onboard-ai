"""Static Super Admin restore UI contracts (no DOM)."""

from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FRONTEND = ROOT / "frontend" / "src"


def test_restore_calls_dedicated_endpoint() -> None:
    api = (FRONTEND / "services" / "superAdminApi.ts").read_text(encoding="utf-8")
    assert "/api/v1/super-admin/users/${employeeId}/restore" in api
    assert "method: 'POST'" in api
    assert "export async function restoreUser" in api
    assert "/api/v1/super-admin/users/${employeeId}/block" in api


def test_hooks_expose_restore_and_invalidate_lists() -> None:
    hooks = (FRONTEND / "hooks" / "useSuperAdmin.ts").read_text(encoding="utf-8")
    assert "mutationFn: (id: string) => api.restoreUser(id)" in hooks
    assert hooks.count("api.restoreUser(id)") == 2
    assert "queryKey: ['super-admin', 'users']" in hooks
    assert "queryKey: ['super-admin', 'companies'" in hooks


def test_users_page_restore_only_for_archived() -> None:
    src = (FRONTEND / "pages" / "super-admin" / "SuperAdminUsersPage.tsx").read_text(
        encoding="utf-8",
    )
    assert "onRestore" in src
    assert "user.status === 'archived'" in src
    assert "t('common.restore')" in src
    assert "t('superAdmin.users.restoreConfirm'" in src
    assert "restore.mutateAsync(user.id)" in src
    assert "{user.status === 'archived' ? (" in src
    assert "t('common.block')" in src
    assert "onBlock" in src


def test_company_detail_restore_only_for_archived() -> None:
    src = (
        FRONTEND / "pages" / "super-admin" / "SuperAdminCompanyDetailPage.tsx"
    ).read_text(encoding="utf-8")
    assert "onRestore" in src
    assert "user.status === 'archived'" in src
    assert "t('common.restore')" in src
    assert "t('superAdmin.companies.detail.restoreConfirm'" in src
    assert "restore.mutateAsync(user.id)" in src
    assert "t('common.block')" in src


def test_restore_copy_exists() -> None:
    ru = (FRONTEND / "i18n" / "ru.ts").read_text(encoding="utf-8")
    assert "restore: 'Восстановить'" in ru
    assert "restoreConfirm: 'Восстановить сотрудника {name}?'" in ru
    assert "restoreSuccess: 'Сотрудник {name} восстановлен.'" in ru

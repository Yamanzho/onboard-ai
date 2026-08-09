import { useAuth } from '../hooks/useAuth'
import { t } from '../i18n'
import { navForWorkspace } from '../lib/navigation'
import { displayRoleLabelKey } from '../lib/workspace'
import { AppShell } from './AppShell'

export function EmployeeLayout() {
  const { user, logout } = useAuth()
  const nav = navForWorkspace('employee')

  return (
    <AppShell
      workspace="employee"
      accent="slate"
      brandLabel={t('workspace.myOnboarding')}
      contextLine={user?.company_name ?? null}
      nav={nav}
      userName={user?.full_name}
      userMeta={`${t(displayRoleLabelKey(user?.role))} · ${user?.email ?? user?.id ?? ''}`}
      onLogout={logout}
      header={
        <header className="flex items-center justify-between border-b border-[var(--color-border)] bg-white px-6 py-3">
          <div>
            <p className="text-sm font-semibold text-[var(--color-text)]">
              {t('workspace.employee')}
            </p>
            <p className="text-xs text-[var(--color-muted)]">
              {user?.company_name ?? t('common.emDash')}
            </p>
          </div>
        </header>
      }
    />
  )
}

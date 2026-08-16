import { useAuth } from '../hooks/useAuth'
import { t } from '../i18n'
import { navForWorkspace } from '../lib/navigation'
import { displayRoleLabelKey } from '../lib/workspace'
import { AppShell } from './AppShell'

export function HrLayout() {
  const { user, logout } = useAuth()
  const nav = navForWorkspace('hr')

  return (
    <AppShell
      workspace="hr"
      accent="cyan"
      brandLabel={t('workspace.hrWorkspace')}
      contextLine={user?.company_name ?? null}
      nav={nav}
      userName={user?.full_name}
      userMeta={`${t(displayRoleLabelKey(user?.role))} · ${user?.email ?? user?.id ?? ''}`}
      onLogout={logout}
      header={
        <header className="hidden items-center justify-between border-b border-[var(--color-border)] bg-white px-6 py-3 md:flex">
          <div>
            <p className="text-sm font-semibold text-[var(--color-text)]">
              {t('workspace.hrWorkspace')}
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

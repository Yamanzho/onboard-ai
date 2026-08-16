import { useSuperAdminAuth } from '../hooks/useSuperAdminAuth'
import { t } from '../i18n'
import { navForWorkspace } from '../lib/navigation'
import { AppShell } from './AppShell'

export function PlatformAdminLayout() {
  const { user, logout } = useSuperAdminAuth()
  const nav = navForWorkspace('platform')

  return (
    <AppShell
      workspace="platform"
      accent="amber"
      brandLabel={t('workspace.platform')}
      contextLine={t('workspace.platformAdmin')}
      nav={nav}
      userName={user?.full_name}
      userMeta={user?.email}
      onLogout={logout}
      header={
        <header className="hidden items-center justify-between border-b border-[var(--color-border)] bg-white px-6 py-3 md:flex">
          <div>
            <p className="text-sm font-semibold text-[var(--color-text)]">
              {t('workspace.platform')}
            </p>
            <p className="text-xs text-[var(--color-muted)]">
              {t('workspace.platformAdmin')}
            </p>
          </div>
        </header>
      }
    />
  )
}

/** @deprecated Prefer PlatformAdminLayout */
export { PlatformAdminLayout as SuperAdminLayout }

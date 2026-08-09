import type { ReactNode } from 'react'
import { NavLink, Outlet } from 'react-router-dom'
import { Button } from '../components/ui/Button'
import { t } from '../i18n'
import type { NavItem } from '../lib/navigation'
import type { WorkspaceId } from '../lib/workspace'

export type AppShellAccent = 'teal' | 'cyan' | 'slate' | 'amber'

const ACCENT_CLASS: Record<AppShellAccent, string> = {
  teal: 'text-teal-300',
  cyan: 'text-cyan-300',
  slate: 'text-slate-300',
  amber: 'text-amber-300',
}

const SIDEBAR_BG: Record<AppShellAccent, string> = {
  teal: 'bg-[var(--color-sidebar)]',
  cyan: 'bg-slate-900',
  slate: 'bg-slate-900',
  amber: 'bg-slate-950',
}

const BORDER: Record<AppShellAccent, string> = {
  teal: 'border-slate-700',
  cyan: 'border-slate-700',
  slate: 'border-slate-700',
  amber: 'border-slate-800',
}

interface AppShellProps {
  workspace: WorkspaceId
  accent?: AppShellAccent
  brandLabel: string
  contextLine?: string | null
  nav: readonly NavItem[]
  userName?: string | null
  userMeta?: string | null
  onLogout: () => void
  /** Optional header strip above main content. */
  header?: ReactNode
}

/**
 * Shared app chrome: sidebar + main. Workspace layouts supply nav + branding.
 */
export function AppShell({
  accent = 'teal',
  brandLabel,
  contextLine,
  nav,
  userName,
  userMeta,
  onLogout,
  header,
}: AppShellProps) {
  return (
    <div className="flex min-h-screen">
      <aside
        className={`flex w-60 shrink-0 flex-col text-slate-200 ${SIDEBAR_BG[accent]}`}
      >
        <div className={`border-b px-5 py-5 ${BORDER[accent]}`}>
          <p
            className={`text-xs font-semibold uppercase tracking-[0.18em] ${ACCENT_CLASS[accent]}`}
          >
            {t('app.brand')}
          </p>
          <p className="mt-1 text-sm font-medium text-white">{brandLabel}</p>
          {contextLine ? (
            <p className="mt-0.5 truncate text-xs text-slate-400">{contextLine}</p>
          ) : null}
        </div>
        <nav className="flex flex-1 flex-col gap-1 p-3">
          {nav.map((item) => (
            <NavLink
              key={`${item.path}:${item.labelKey}`}
              to={item.path}
              end={item.path === '/company' || item.path === '/hr' || item.path === '/employee' || item.path === '/platform'}
              className={({ isActive }) =>
                `rounded-md px-3 py-2 text-sm transition ${
                  isActive
                    ? 'bg-slate-800 text-white'
                    : 'text-slate-300 hover:bg-slate-800/60 hover:text-white'
                }`
              }
            >
              {t(item.labelKey)}
            </NavLink>
          ))}
        </nav>
        <div className={`border-t p-4 ${BORDER[accent]}`}>
          <p className="truncate text-sm font-medium text-white">{userName}</p>
          {userMeta ? (
            <p className="truncate text-xs text-slate-400">{userMeta}</p>
          ) : null}
          <Button
            variant="ghost"
            className="mt-3 w-full justify-start px-0 text-slate-300 hover:text-white"
            onClick={onLogout}
          >
            {t('common.signOut')}
          </Button>
        </div>
      </aside>
      <div className="flex min-w-0 flex-1 flex-col">
        {header}
        <main className="flex-1 overflow-auto bg-[var(--color-bg)] p-6 md:p-8">
          <Outlet />
        </main>
      </div>
    </div>
  )
}

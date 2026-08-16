import type { ReactNode } from 'react'
import { useState } from 'react'
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
  const [navOpen, setNavOpen] = useState(false)

  return (
    <div className="flex min-h-screen">
      {navOpen ? (
        <button
          type="button"
          className="fixed inset-0 z-30 bg-black/40 md:hidden"
          aria-label={t('common.closeMenu')}
          onClick={() => setNavOpen(false)}
        />
      ) : null}
      <aside
        className={`fixed inset-y-0 left-0 z-40 flex w-60 shrink-0 flex-col text-slate-200 transition-transform md:static md:translate-x-0 ${SIDEBAR_BG[accent]} ${
          navOpen ? 'translate-x-0' : '-translate-x-full'
        }`}
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
              onClick={() => setNavOpen(false)}
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
        <div className="flex items-center gap-3 border-b border-[var(--color-border)] bg-white px-4 py-3 md:hidden">
          <button
            type="button"
            className="rounded-md border border-[var(--color-border)] px-3 py-1.5 text-sm"
            aria-label={t('common.openMenu')}
            onClick={() => setNavOpen(true)}
          >
            {t('common.menu')}
          </button>
          <p className="truncate text-sm font-semibold">{brandLabel}</p>
        </div>
        {header}
        <main className="flex-1 overflow-auto bg-[var(--color-bg)] p-4 md:p-8">
          <Outlet />
        </main>
      </div>
    </div>
  )
}

import { NavLink, Outlet } from 'react-router-dom'
import { useSuperAdminAuth } from '../hooks/useSuperAdminAuth'
import { Button } from '../components/ui/Button'
import { t } from '../i18n'
import { navForRole } from '../lib/navigation'

export function SuperAdminLayout() {
  const { user, logout } = useSuperAdminAuth()
  const nav = navForRole('super_admin')

  return (
    <div className="flex min-h-screen">
      <aside className="flex w-60 shrink-0 flex-col bg-slate-950 text-slate-200">
        <div className="border-b border-slate-800 px-5 py-5">
          <p className="text-xs font-semibold uppercase tracking-[0.18em] text-amber-300">
            {t('app.brand')}
          </p>
          <p className="mt-1 text-sm text-slate-400">{t('app.superAdmin')}</p>
        </div>
        <nav className="flex flex-1 flex-col gap-1 p-3">
          {nav.map((item) => (
            <NavLink
              key={item.path}
              to={item.path}
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
        <div className="border-t border-slate-800 p-4">
          <p className="truncate text-sm font-medium text-white">
            {user?.full_name}
          </p>
          <p className="truncate text-xs text-slate-400">{user?.email}</p>
          <Button
            variant="ghost"
            className="mt-3 w-full justify-start px-0 text-slate-300 hover:text-white"
            onClick={logout}
          >
            {t('common.signOut')}
          </Button>
        </div>
      </aside>
      <main className="flex-1 overflow-auto bg-[var(--color-bg)] p-6 md:p-8">
        <Outlet />
      </main>
    </div>
  )
}

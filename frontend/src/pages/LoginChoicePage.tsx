import { Navigate, Link } from 'react-router-dom'
import { Button } from '../components/ui/Button'
import { useAuth } from '../hooks/useAuth'
import { useSuperAdminAuth } from '../hooks/useSuperAdminAuth'
import { homePathForRole } from '../lib/navigation'
import { t } from '../i18n'

const LOGIN_OPTIONS = [
  { path: '/admin/login', labelKey: 'workspace.companyAdmin' },
  { path: '/hr/login', labelKey: 'workspace.hr' },
  { path: '/employee/login', labelKey: 'workspace.employee' },
  { path: '/super-admin/login', labelKey: 'workspace.platformAdmin' },
] as const

export function LoginChoicePage() {
  const { user, loading, isAuthenticated } = useAuth()
  const {
    loading: saLoading,
    isAuthenticated: saAuthenticated,
  } = useSuperAdminAuth()

  if (loading || saLoading) {
    return (
      <p className="text-center text-sm text-[var(--color-muted)]">
        {t('common.loading')}
      </p>
    )
  }

  if (saAuthenticated) {
    return <Navigate to={homePathForRole('super_admin')} replace />
  }

  if (isAuthenticated && user) {
    return <Navigate to={homePathForRole(user.role)} replace />
  }

  return (
    <div className="rounded-xl border border-[var(--color-border)] bg-white p-6 shadow-sm">
      <h2 className="text-lg font-semibold">{t('auth.chooseWorkspace')}</h2>
      <div className="mt-5 grid gap-3">
        {LOGIN_OPTIONS.map((option) => (
          <Link key={option.path} to={option.path}>
            <Button className="w-full" variant="secondary">
              {t(option.labelKey)}
            </Button>
          </Link>
        ))}
      </div>
    </div>
  )
}

import { Navigate, Outlet } from 'react-router-dom'
import { useSuperAdminAuth } from '../hooks/useSuperAdminAuth'
import { t } from '../i18n'

export function SuperAdminProtectedRoute() {
  const { isAuthenticated, loading } = useSuperAdminAuth()

  if (loading) {
    return (
      <div className="flex min-h-screen items-center justify-center text-sm text-[var(--color-muted)]">
        {t('common.loading')}
      </div>
    )
  }

  if (!isAuthenticated) {
    return <Navigate to="/super-admin/login" replace />
  }

  return <Outlet />
}

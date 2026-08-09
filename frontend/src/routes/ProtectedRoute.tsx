import { Navigate, Outlet } from 'react-router-dom'
import { useAuth } from '../hooks/useAuth'
import { useSuperAdminAuth } from '../hooks/useSuperAdminAuth'
import { homePathForRole } from '../lib/navigation'
import { t } from '../i18n'

export function ProtectedRoute() {
  const { isAuthenticated, loading } = useAuth()
  const {
    isAuthenticated: saAuth,
    loading: saLoading,
  } = useSuperAdminAuth()

  if (loading || saLoading) {
    return (
      <div className="flex min-h-screen items-center justify-center text-sm text-[var(--color-muted)]">
        {t('common.loading')}
      </div>
    )
  }

  if (!isAuthenticated) {
    if (saAuth) {
      return <Navigate to={homePathForRole('super_admin')} replace />
    }
    return <Navigate to="/login" replace />
  }

  return <Outlet />
}

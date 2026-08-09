import { Navigate, Outlet } from 'react-router-dom'
import { useAuth } from '../hooks/useAuth'
import { useSuperAdminAuth } from '../hooks/useSuperAdminAuth'
import { homePathForRole } from '../lib/navigation'
import { t } from '../i18n'

export function SuperAdminProtectedRoute() {
  const { isAuthenticated, loading } = useSuperAdminAuth()
  const {
    user,
    isAuthenticated: tenantAuth,
    loading: tenantLoading,
  } = useAuth()

  if (loading || tenantLoading) {
    return (
      <div className="flex min-h-screen items-center justify-center text-sm text-[var(--color-muted)]">
        {t('common.loading')}
      </div>
    )
  }

  if (!isAuthenticated) {
    // Tenant user hitting /platform must land in their workspace, not SA login.
    if (tenantAuth && user) {
      return <Navigate to={homePathForRole(user.role)} replace />
    }
    return <Navigate to="/super-admin/login" replace />
  }

  return <Outlet />
}

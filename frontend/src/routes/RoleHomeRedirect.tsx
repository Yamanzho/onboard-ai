import { Navigate } from 'react-router-dom'
import { useAuth } from '../hooks/useAuth'
import { useSuperAdminAuth } from '../hooks/useSuperAdminAuth'
import { homePathForRole } from '../lib/navigation'
import { t } from '../i18n'

/** Role-aware default redirect for `/` and unknown paths. */
export function RoleHomeRedirect() {
  const { user, loading, isAuthenticated } = useAuth()
  const {
    user: saUser,
    loading: saLoading,
    isAuthenticated: saAuth,
  } = useSuperAdminAuth()

  if (loading || saLoading) {
    return (
      <div className="flex min-h-screen items-center justify-center text-sm text-[var(--color-muted)]">
        {t('common.loading')}
      </div>
    )
  }

  if (saAuth && saUser) {
    return <Navigate to={homePathForRole('super_admin')} replace />
  }

  if (isAuthenticated && user) {
    return <Navigate to={homePathForRole(user.role)} replace />
  }

  return <Navigate to="/" replace />
}

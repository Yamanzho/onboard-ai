import { Navigate, Outlet, useLocation } from 'react-router-dom'
import { useAuth } from '../hooks/useAuth'
import { t } from '../i18n'
import { homePathForRole, roleAllowed, type AppRole } from '../lib/navigation'
import { loginPathForPathname } from '../lib/workspace'

interface RequireRoleProps {
  allowed: readonly AppRole[]
  /** Override redirect target when role does not match. */
  redirectTo?: string
}

/**
 * Route guard: authenticated tenant user must have one of `allowed` roles.
 * UI-only — backend authorization remains authoritative.
 */
export function RequireRole({ allowed, redirectTo }: RequireRoleProps) {
  const { pathname } = useLocation()
  const { user, loading, isAuthenticated } = useAuth()

  if (loading) {
    return (
      <div className="flex min-h-screen items-center justify-center text-sm text-[var(--color-muted)]">
        {t('common.loading')}
      </div>
    )
  }

  if (!isAuthenticated || !user) {
    return <Navigate to={loginPathForPathname(pathname)} replace />
  }

  if (!roleAllowed(user.role, allowed)) {
    return (
      <Navigate to={redirectTo ?? homePathForRole(user.role)} replace />
    )
  }

  return <Outlet />
}

/** Alias matching sprint naming. */
export function RequireAnyRole(props: RequireRoleProps) {
  return <RequireRole {...props} />
}

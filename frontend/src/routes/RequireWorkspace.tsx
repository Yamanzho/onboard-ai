import { Navigate, Outlet } from 'react-router-dom'
import { useAuth } from '../hooks/useAuth'
import { useSuperAdminAuth } from '../hooks/useSuperAdminAuth'
import { t } from '../i18n'
import { homePathForRole } from '../lib/navigation'
import {
  loginPathForWorkspace,
  roleOwnsWorkspace,
  type WorkspaceId,
} from '../lib/workspace'

interface RequireWorkspaceProps {
  workspace: WorkspaceId
}

/**
 * Route guard: user must belong to the given frontend workspace.
 * UI-only — backend RBAC/RLS remain authoritative.
 */
export function RequireWorkspace({ workspace }: RequireWorkspaceProps) {
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

  if (workspace === 'platform') {
    if (saAuth && saUser) {
      return <Outlet />
    }
    if (isAuthenticated && user) {
      return <Navigate to={homePathForRole(user.role)} replace />
    }
    return <Navigate to={loginPathForWorkspace('platform')} replace />
  }

  if (!isAuthenticated || !user) {
    if (saAuth && saUser) {
      return <Navigate to={homePathForRole('super_admin')} replace />
    }
    return <Navigate to={loginPathForWorkspace(workspace)} replace />
  }

  if (!roleOwnsWorkspace(user.role, workspace)) {
    return <Navigate to={homePathForRole(user.role)} replace />
  }

  return <Outlet />
}

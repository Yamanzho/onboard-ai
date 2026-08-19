import type { EmployeeRole } from '../types/auth'
import type { AppRole } from './navigation'

/** Explicit frontend workspace — not derived from allowedRoles alone. */
export type WorkspaceId = 'platform' | 'company' | 'hr' | 'employee'

export const WORKSPACE_BASE: Record<WorkspaceId, string> = {
  platform: '/platform',
  company: '/company',
  hr: '/hr',
  employee: '/employee',
} as const

export const WORKSPACE_LOGIN: Record<WorkspaceId, string> = {
  platform: '/super-admin/login',
  company: '/admin/login',
  hr: '/hr/login',
  employee: '/employee/login',
} as const

export const ROLE_WORKSPACE: Record<AppRole, WorkspaceId> = {
  super_admin: 'platform',
  admin: 'company',
  hr: 'hr',
  employee: 'employee',
}

/** Human-facing workspace title key (header / sidebar). */
export function workspaceTitleKey(workspace: WorkspaceId): string {
  switch (workspace) {
    case 'platform':
      return 'workspace.platform'
    case 'company':
      return 'workspace.companyAdmin'
    case 'hr':
      return 'workspace.hr'
    case 'employee':
      return 'workspace.employee'
  }
}

/** Friendly role label for UI (never show raw ADMIN). */
export function displayRoleLabelKey(role: AppRole | string | null | undefined): string {
  switch (role) {
    case 'super_admin':
      return 'workspace.platformAdmin'
    case 'admin':
      return 'workspace.companyAdmin'
    case 'hr':
      return 'workspace.hr'
    case 'employee':
      return 'workspace.employee'
    default:
      return 'app.admin'
  }
}

export function workspaceForRole(
  role: AppRole | EmployeeRole | string | null | undefined,
): WorkspaceId | null {
  if (!role) return null
  return ROLE_WORKSPACE[role as AppRole] ?? null
}

export function workspaceBaseForRole(
  role: AppRole | EmployeeRole | string | null | undefined,
): string {
  const ws = workspaceForRole(role)
  return ws ? WORKSPACE_BASE[ws] : '/'
}

export function loginPathForWorkspace(workspace: WorkspaceId): string {
  return WORKSPACE_LOGIN[workspace]
}

export function loginPathForRole(
  role: AppRole | EmployeeRole | string | null | undefined,
): string {
  const workspace = workspaceForRole(role)
  return workspace ? WORKSPACE_LOGIN[workspace] : '/'
}

export function loginPathForPathname(pathname: string): string {
  if (pathname.startsWith('/company')) return WORKSPACE_LOGIN.company
  if (pathname.startsWith('/hr')) return WORKSPACE_LOGIN.hr
  if (pathname.startsWith('/employee')) return WORKSPACE_LOGIN.employee
  if (pathname.startsWith('/platform')) return WORKSPACE_LOGIN.platform
  return '/'
}

export function roleOwnsWorkspace(
  role: AppRole | string | null | undefined,
  workspace: WorkspaceId,
): boolean {
  return workspaceForRole(role) === workspace
}

/** Join workspace base with a relative path segment. */
export function workspacePath(
  workspace: WorkspaceId,
  rest = '',
): string {
  const base = WORKSPACE_BASE[workspace]
  if (!rest || rest === '/') return base
  const normalized = rest.startsWith('/') ? rest : `/${rest}`
  return `${base}${normalized}`
}

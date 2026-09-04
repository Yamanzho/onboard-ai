import type { EmployeeRole } from '../types/auth'
import {
  ROLE_WORKSPACE,
  WORKSPACE_BASE,
  type WorkspaceId,
  workspacePath,
} from './workspace'

export type AppRole = EmployeeRole | 'super_admin'

export interface NavItem {
  path: string
  labelKey: string
  icon?: string
  /** Roles that may see this item (defense in depth; workspace is primary). */
  allowedRoles: readonly AppRole[]
  workspace: WorkspaceId
}

/** Company Admin workspace navigation. */
export const COMPANY_NAV: readonly NavItem[] = [
  {
    path: workspacePath('company'),
    labelKey: 'nav.dashboard',
    icon: 'dashboard',
    allowedRoles: ['admin'],
    workspace: 'company',
  },
    {
      path: workspacePath('company', '/employees'),
      labelKey: 'nav.employees',
      icon: 'employees',
      allowedRoles: ['admin'],
      workspace: 'company',
    },
    {
      path: workspacePath('company', '/departments'),
      labelKey: 'nav.departments',
      icon: 'employees',
      allowedRoles: ['admin'],
      workspace: 'company',
    },
    {
      path: workspacePath('company', '/topics'),
      labelKey: 'nav.topics',
      icon: 'knowledge',
      allowedRoles: ['admin'],
      workspace: 'company',
    },
  {
    path: workspacePath('company', '/hr'),
    labelKey: 'nav.hr',
    icon: 'hr',
    allowedRoles: ['admin'],
    workspace: 'company',
  },
  {
    path: workspacePath('company', '/onboarding'),
    labelKey: 'nav.onboarding',
    icon: 'programs',
    allowedRoles: ['admin'],
    workspace: 'company',
  },
  {
    path: workspacePath('company', '/assignments'),
    labelKey: 'nav.assignments',
    icon: 'assignments',
    allowedRoles: ['admin'],
    workspace: 'company',
  },
  {
    path: workspacePath('company', '/knowledge'),
    labelKey: 'nav.knowledgeBase',
    icon: 'knowledge',
    allowedRoles: ['admin'],
    workspace: 'company',
  },
    {
      path: workspacePath('company', '/progress'),
      labelKey: 'nav.progress',
      icon: 'progress',
      allowedRoles: ['admin'],
      workspace: 'company',
    },
    {
      path: workspacePath('company', '/audit'),
      labelKey: 'nav.auditLog',
      icon: 'audit',
      allowedRoles: ['admin'],
      workspace: 'company',
    },
  {
    path: workspacePath('company', '/settings'),
    labelKey: 'nav.companySettings',
    icon: 'company-settings',
    allowedRoles: ['admin'],
    workspace: 'company',
  },
  {
    path: workspacePath('company', '/profile'),
    labelKey: 'nav.profile',
    icon: 'profile',
    allowedRoles: ['admin'],
    workspace: 'company',
  },
  {
    path: workspacePath('company', '/security'),
    labelKey: 'nav.security',
    icon: 'security',
    allowedRoles: ['admin'],
    workspace: 'company',
  },
] as const

/** HR workspace navigation. */
export const HR_NAV: readonly NavItem[] = [
  {
    path: workspacePath('hr'),
    labelKey: 'nav.dashboard',
    icon: 'dashboard',
    allowedRoles: ['hr'],
    workspace: 'hr',
  },
    {
      path: workspacePath('hr', '/employees'),
      labelKey: 'nav.employees',
      icon: 'employees',
      allowedRoles: ['hr'],
      workspace: 'hr',
    },
    {
      path: workspacePath('hr', '/departments'),
      labelKey: 'nav.departments',
      icon: 'employees',
      allowedRoles: ['hr'],
      workspace: 'hr',
    },
    {
      path: workspacePath('hr', '/topics'),
      labelKey: 'nav.topics',
      icon: 'knowledge',
      allowedRoles: ['hr'],
      workspace: 'hr',
    },
  {
    path: workspacePath('hr', '/onboarding'),
    labelKey: 'nav.onboarding',
    icon: 'programs',
    allowedRoles: ['hr'],
    workspace: 'hr',
  },
  {
    path: workspacePath('hr', '/assignments'),
    labelKey: 'nav.assignments',
    icon: 'assignments',
    allowedRoles: ['hr'],
    workspace: 'hr',
  },
  {
    path: workspacePath('hr', '/knowledge'),
    labelKey: 'nav.knowledgeBase',
    icon: 'knowledge',
    allowedRoles: ['hr'],
    workspace: 'hr',
  },
    {
      path: workspacePath('hr', '/progress'),
      labelKey: 'nav.progress',
      icon: 'progress',
      allowedRoles: ['hr'],
      workspace: 'hr',
    },
    {
      path: workspacePath('hr', '/audit'),
      labelKey: 'nav.auditLog',
      icon: 'audit',
      allowedRoles: ['hr'],
      workspace: 'hr',
    },
  {
    path: workspacePath('hr', '/profile'),
    labelKey: 'nav.profile',
    icon: 'profile',
    allowedRoles: ['hr'],
    workspace: 'hr',
  },
  {
    path: workspacePath('hr', '/security'),
    labelKey: 'nav.security',
    icon: 'security',
    allowedRoles: ['hr'],
    workspace: 'hr',
  },
] as const

/** Employee web cabinet navigation. */
export const EMPLOYEE_NAV: readonly NavItem[] = [
  {
    path: workspacePath('employee'),
    labelKey: 'nav.dashboard',
    icon: 'dashboard',
    allowedRoles: ['employee'],
    workspace: 'employee',
  },
  {
    path: workspacePath('employee', '/onboarding'),
    labelKey: 'nav.myOnboarding',
    icon: 'onboarding',
    allowedRoles: ['employee'],
    workspace: 'employee',
  },
  {
    path: workspacePath('employee', '/active'),
    labelKey: 'nav.active',
    icon: 'active',
    allowedRoles: ['employee'],
    workspace: 'employee',
  },
  {
    path: workspacePath('employee', '/history'),
    labelKey: 'nav.history',
    icon: 'history',
    allowedRoles: ['employee'],
    workspace: 'employee',
  },
  {
    path: workspacePath('employee', '/calendar'),
    labelKey: 'nav.calendar',
    icon: 'calendar',
    allowedRoles: ['employee'],
    workspace: 'employee',
  },
  {
    path: workspacePath('employee', '/company'),
    labelKey: 'nav.company',
    icon: 'company',
    allowedRoles: ['employee'],
    workspace: 'employee',
  },
  {
    path: workspacePath('employee', '/knowledge'),
    labelKey: 'nav.knowledgeBase',
    icon: 'knowledge',
    allowedRoles: ['employee'],
    workspace: 'employee',
  },
  {
    path: workspacePath('employee', '/ai'),
    labelKey: 'nav.aiAssistant',
    icon: 'ai',
    allowedRoles: ['employee'],
    workspace: 'employee',
  },
  {
    path: workspacePath('employee', '/profile'),
    labelKey: 'nav.profile',
    icon: 'profile',
    allowedRoles: ['employee'],
    workspace: 'employee',
  },
  {
    path: workspacePath('employee', '/security'),
    labelKey: 'nav.security',
    icon: 'security',
    allowedRoles: ['employee'],
    workspace: 'employee',
  },
] as const

/** Platform (Super Admin) navigation. */
export const PLATFORM_NAV: readonly NavItem[] = [
  {
    path: workspacePath('platform'),
    labelKey: 'nav.dashboard',
    icon: 'dashboard',
    allowedRoles: ['super_admin'],
    workspace: 'platform',
  },
  {
    path: workspacePath('platform', '/companies'),
    labelKey: 'nav.companies',
    icon: 'companies',
    allowedRoles: ['super_admin'],
    workspace: 'platform',
  },
  {
    path: workspacePath('platform', '/users'),
    labelKey: 'nav.users',
    icon: 'users',
    allowedRoles: ['super_admin'],
    workspace: 'platform',
  },
  {
    path: workspacePath('platform', '/subscriptions'),
    labelKey: 'nav.subscriptions',
    icon: 'subscriptions',
    allowedRoles: ['super_admin'],
    workspace: 'platform',
  },
  {
    path: workspacePath('platform', '/audit'),
    labelKey: 'nav.auditLog',
    icon: 'audit',
    allowedRoles: ['super_admin'],
    workspace: 'platform',
  },
  {
    path: workspacePath('platform', '/settings'),
    labelKey: 'nav.platformSettings',
    icon: 'settings',
    allowedRoles: ['super_admin'],
    workspace: 'platform',
  },
] as const

const NAV_BY_WORKSPACE: Record<WorkspaceId, readonly NavItem[]> = {
  company: COMPANY_NAV,
  hr: HR_NAV,
  employee: EMPLOYEE_NAV,
  platform: PLATFORM_NAV,
}

/** @deprecated Prefer navForWorkspace — kept for call-site compatibility. */
export const TENANT_NAV: readonly NavItem[] = [
  ...COMPANY_NAV,
  ...HR_NAV,
  ...EMPLOYEE_NAV,
]

/** @deprecated Prefer PLATFORM_NAV */
export const SUPER_ADMIN_NAV = PLATFORM_NAV

export function navForWorkspace(workspace: WorkspaceId): NavItem[] {
  return [...NAV_BY_WORKSPACE[workspace]]
}

export function navForRole(role: AppRole | string | null | undefined): NavItem[] {
  if (!role) return []
  const workspace = ROLE_WORKSPACE[role as AppRole]
  if (!workspace) return []
  return navForWorkspace(workspace).filter((item) =>
    item.allowedRoles.includes(role as AppRole),
  )
}

export function homePathForRole(role: AppRole | string | null | undefined): string {
  switch (role) {
    case 'super_admin':
      return WORKSPACE_BASE.platform
    case 'admin':
      return WORKSPACE_BASE.company
    case 'hr':
      return WORKSPACE_BASE.hr
    case 'employee':
      return WORKSPACE_BASE.employee
    default:
      return '/'
  }
}

export function roleAllowed(
  role: AppRole | string | null | undefined,
  allowed: readonly AppRole[],
): boolean {
  if (!role) return false
  return allowed.includes(role as AppRole)
}

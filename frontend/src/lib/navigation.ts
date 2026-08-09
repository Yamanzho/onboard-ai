import type { EmployeeRole } from '../types/auth'

export type AppRole = EmployeeRole | 'super_admin'

export interface NavItem {
  path: string
  labelKey: string
  icon?: string
  allowedRoles: readonly AppRole[]
}

/** Central role-aware navigation. Sidebar filters by `allowedRoles`. */
export const TENANT_NAV: readonly NavItem[] = [
  {
    path: '/dashboard',
    labelKey: 'nav.companyDashboard',
    icon: 'dashboard',
    allowedRoles: ['admin'],
  },
  {
    path: '/dashboard',
    labelKey: 'nav.hrDashboard',
    icon: 'dashboard',
    allowedRoles: ['hr'],
  },
  {
    path: '/my-onboarding',
    labelKey: 'nav.myOnboarding',
    icon: 'onboarding',
    allowedRoles: ['employee'],
  },
  {
    path: '/my/active',
    labelKey: 'nav.active',
    icon: 'active',
    allowedRoles: ['employee'],
  },
  {
    path: '/my/history',
    labelKey: 'nav.history',
    icon: 'history',
    allowedRoles: ['employee'],
  },
  {
    path: '/my/calendar',
    labelKey: 'nav.calendar',
    icon: 'calendar',
    allowedRoles: ['employee'],
  },
  {
    path: '/my/company',
    labelKey: 'nav.company',
    icon: 'company',
    allowedRoles: ['employee'],
  },
  {
    path: '/employees',
    labelKey: 'nav.employees',
    icon: 'employees',
    allowedRoles: ['admin', 'hr'],
  },
  {
    path: '/onboarding',
    labelKey: 'nav.onboarding',
    icon: 'programs',
    allowedRoles: ['admin', 'hr'],
  },
  {
    path: '/assignments',
    labelKey: 'nav.assignments',
    icon: 'assignments',
    allowedRoles: ['admin', 'hr'],
  },
  {
    path: '/knowledge/articles',
    labelKey: 'nav.knowledgeBase',
    icon: 'knowledge',
    allowedRoles: ['admin', 'hr'],
  },
  {
    path: '/knowledge/categories',
    labelKey: 'nav.categories',
    icon: 'categories',
    allowedRoles: ['admin', 'hr'],
  },
  {
    path: '/knowledge/tags',
    labelKey: 'nav.tags',
    icon: 'tags',
    allowedRoles: ['admin', 'hr'],
  },
  {
    path: '/company-settings',
    labelKey: 'nav.companySettings',
    icon: 'company-settings',
    allowedRoles: ['admin'],
  },
  {
    path: '/profile',
    labelKey: 'nav.profile',
    icon: 'profile',
    allowedRoles: ['admin', 'hr', 'employee'],
  },
  {
    path: '/security',
    labelKey: 'nav.security',
    icon: 'security',
    allowedRoles: ['admin', 'hr', 'employee'],
  },
] as const

export const SUPER_ADMIN_NAV: readonly NavItem[] = [
  {
    path: '/super-admin/dashboard',
    labelKey: 'nav.dashboard',
    icon: 'dashboard',
    allowedRoles: ['super_admin'],
  },
  {
    path: '/super-admin/companies',
    labelKey: 'nav.companies',
    icon: 'companies',
    allowedRoles: ['super_admin'],
  },
  {
    path: '/super-admin/users',
    labelKey: 'nav.users',
    icon: 'users',
    allowedRoles: ['super_admin'],
  },
  {
    path: '/super-admin/subscriptions',
    labelKey: 'nav.subscriptions',
    icon: 'subscriptions',
    allowedRoles: ['super_admin'],
  },
  {
    path: '/super-admin/audit-log',
    labelKey: 'nav.auditLog',
    icon: 'audit',
    allowedRoles: ['super_admin'],
  },
  {
    path: '/super-admin/settings',
    labelKey: 'nav.settings',
    icon: 'settings',
    allowedRoles: ['super_admin'],
  },
] as const

export function navForRole(role: AppRole | string | null | undefined): NavItem[] {
  if (!role) return []
  const items = role === 'super_admin' ? SUPER_ADMIN_NAV : TENANT_NAV
  return items.filter((item) =>
    item.allowedRoles.includes(role as AppRole),
  )
}

export function homePathForRole(role: AppRole | string | null | undefined): string {
  switch (role) {
    case 'super_admin':
      return '/super-admin/dashboard'
    case 'employee':
      return '/my-onboarding'
    case 'admin':
    case 'hr':
      return '/dashboard'
    default:
      return '/login'
  }
}

export function roleAllowed(
  role: AppRole | string | null | undefined,
  allowed: readonly AppRole[],
): boolean {
  if (!role) return false
  return allowed.includes(role as AppRole)
}

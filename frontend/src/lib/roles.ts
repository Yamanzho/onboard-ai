import type { EmployeeRole } from '../types/auth'
import type { AppRole } from './navigation'

/** Roles that may use the tenant web app (Admin / HR / Employee panels). */
const PANEL_ROLES = new Set<string>(['admin', 'hr', 'employee'])

/** Admin/HR company management panel (legacy name kept for call sites). */
export function canAccessAdminPanel(role: EmployeeRole | string): boolean {
  return role === 'admin' || role === 'hr'
}

export function canAccessTenantPanel(role: EmployeeRole | string): boolean {
  return PANEL_ROLES.has(role)
}

export function isEmployeeRole(role: EmployeeRole | string): boolean {
  return role === 'employee'
}

export function isHrOrAdmin(role: EmployeeRole | string): boolean {
  return role === 'admin' || role === 'hr'
}

export function panelLabelKey(role: AppRole | string | null | undefined): string {
  switch (role) {
    case 'super_admin':
      return 'app.superAdmin'
    case 'admin':
      return 'app.adminPanel'
    case 'hr':
      return 'app.hrPanel'
    case 'employee':
      return 'app.employeePanel'
    default:
      return 'app.admin'
  }
}

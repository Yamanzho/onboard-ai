import type { EmployeeRole } from '../types/auth'

const PANEL_ROLES = new Set<string>(['admin', 'hr'])

export function canAccessAdminPanel(role: EmployeeRole | string): boolean {
  return PANEL_ROLES.has(role)
}

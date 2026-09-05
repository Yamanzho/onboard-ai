import type { CurrentUser } from '../types/auth'

/** Server-resolved capability strings. Display-only on the client. */
export const CAPABILITIES = {
  EMPLOYEES_VIEW: 'employees.view',
  EMPLOYEES_MANAGE: 'employees.manage',
  DEPARTMENTS_VIEW: 'departments.view',
  DEPARTMENTS_MANAGE: 'departments.manage',
  COURSES_VIEW: 'courses.view',
  COURSES_CREATE: 'courses.create',
  COURSES_EDIT: 'courses.edit',
  COURSES_ASSIGN: 'courses.assign',
  ASSIGNMENTS_VIEW_ALL: 'assignments.view_all',
  ASSIGNMENTS_VIEW_DEPARTMENT: 'assignments.view_department',
  ASSIGNMENTS_VIEW_OWN: 'assignments.view_own',
  ASSIGNMENTS_MANAGE: 'assignments.manage',
  DEADLINES_MANAGE: 'deadlines.manage',
  PROGRESS_VIEW_ALL: 'progress.view_all',
  PROGRESS_VIEW_DEPARTMENT: 'progress.view_department',
  PROGRESS_VIEW_OWN: 'progress.view_own',
  KNOWLEDGE_VIEW: 'knowledge.view',
  KNOWLEDGE_MANAGE: 'knowledge.manage',
  RESPONSIBILITIES_VIEW: 'responsibilities.view',
  RESPONSIBILITIES_MANAGE: 'responsibilities.manage',
  ANALYTICS_VIEW: 'analytics.view',
  COMPANY_SETTINGS_MANAGE: 'company.settings.manage',
} as const

export type Capability = (typeof CAPABILITIES)[keyof typeof CAPABILITIES]

export function hasCapability(
  user: CurrentUser | null | undefined,
  capability: string,
): boolean {
  return Boolean(user?.capabilities?.includes(capability))
}

export function can(
  user: CurrentUser | null | undefined,
  capability: string,
): boolean {
  return hasCapability(user, capability)
}

export function userCapabilities(
  user: CurrentUser | null | undefined,
): readonly string[] {
  return user?.capabilities ?? []
}

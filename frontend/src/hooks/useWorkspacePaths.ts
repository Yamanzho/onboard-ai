import { useAuth } from './useAuth'
import {
  WORKSPACE_BASE,
  workspaceForRole,
  workspacePath,
  type WorkspaceId,
} from '../lib/workspace'

/**
 * Path builders scoped to the current user's workspace.
 * Shared pages (employees, onboarding, …) use this instead of hardcoded roots.
 */
export function useWorkspacePaths() {
  const { user } = useAuth()
  const workspace = (workspaceForRole(user?.role) ?? 'company') as WorkspaceId
  const base = WORKSPACE_BASE[workspace]

  function path(rest = ''): string {
    return workspacePath(workspace, rest)
  }

  return {
    workspace,
    base,
    path,
    dashboard: path(),
    employees: path('/employees'),
    departments: path('/departments'),
    topics: path('/topics'),
    employee: (id: string) => path(`/employees/${id}`),
    employeeNew: path('/employees/new'),
    employeeEdit: (id: string) => path(`/employees/${id}/edit`),
    hr: path('/hr'),
    hrNew: path('/hr/create'),
    hrDetail: (id: string) => path(`/hr/${id}`),
    onboarding: path('/onboarding'),
    onboardingNew: path('/onboarding/new'),
    program: (id: string) => path(`/onboarding/${id}`),
    programEdit: (id: string) => path(`/onboarding/${id}/edit`),
    assignments: path('/assignments'),
    assignmentNew: path('/assignments/new'),
    assignment: (id: string) => path(`/assignments/${id}`),
    knowledge: path('/knowledge'),
    knowledgeNew: path('/knowledge/new'),
    article: (id: string) => path(`/knowledge/${id}`),
    ai: path('/ai'),
    categories: path('/knowledge/categories'),
    tags: path('/knowledge/tags'),
    progress: path('/progress'),
    analytics: path('/analytics'),
    audit: path('/audit'),
    settings: path('/settings'),
    profile: path('/profile'),
    security: path('/security'),
  }
}

export function usePlatformPaths() {
  const base = WORKSPACE_BASE.platform
  function path(rest = ''): string {
    return workspacePath('platform', rest)
  }
  return {
    workspace: 'platform' as const,
    base,
    path,
    dashboard: path(),
    companies: path('/companies'),
    companyNew: path('/companies/new'),
    company: (id: string) => path(`/companies/${id}`),
    companyEdit: (id: string) => path(`/companies/${id}/edit`),
    users: path('/users'),
    subscriptions: path('/subscriptions'),
    audit: path('/audit'),
    settings: path('/settings'),
  }
}

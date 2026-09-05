import type { AssignmentAnalytics, OnboardingAnalytics } from '../types/analytics'
import { apiRequest } from './apiClient'

export async function getOnboardingAnalytics(
  companyId: string,
  filters: { departmentId?: string } = {},
): Promise<OnboardingAnalytics> {
  const search = new URLSearchParams({ company_id: companyId })
  if (filters.departmentId) search.set('department_id', filters.departmentId)
  return apiRequest<OnboardingAnalytics>(
    `/api/v1/analytics/onboarding?${search}`,
  )
}

export async function getAssignmentAnalytics(
  companyId: string,
  filters: { departmentId?: string; assignmentType?: string } = {},
): Promise<AssignmentAnalytics> {
  const search = new URLSearchParams({ company_id: companyId })
  if (filters.departmentId) search.set('department_id', filters.departmentId)
  if (filters.assignmentType) search.set('assignment_type', filters.assignmentType)
  return apiRequest<AssignmentAnalytics>(
    `/api/v1/analytics/assignments?${search}`,
  )
}

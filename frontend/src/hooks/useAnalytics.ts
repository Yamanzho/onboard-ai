import { useQuery } from '@tanstack/react-query'
import { getAssignmentAnalytics, getOnboardingAnalytics } from '../services/analyticsApi'
import { listCompanyAuditLogs } from '../services/companyAuditApi'
import { useAuth } from './useAuth'

export function useOnboardingAnalytics() {
  const { user } = useAuth()
  const companyId = user?.company_id
  return useQuery({
    queryKey: ['onboarding-analytics', companyId],
    queryFn: () => getOnboardingAnalytics(companyId!),
    enabled: Boolean(companyId),
  })
}

export function useAssignmentAnalytics(filters: {
  departmentId?: string
  assignmentType?: string
} = {}) {
  const { user } = useAuth()
  const companyId = user?.company_id
  return useQuery({
    queryKey: ['assignment-analytics', companyId, filters],
    queryFn: () => getAssignmentAnalytics(companyId!, filters),
    enabled: Boolean(companyId),
  })
}

export function useCompanyAuditLogs(filters: {
  action?: string
  resource_type?: string
} = {}) {
  const { user } = useAuth()
  const companyId = user?.company_id
  return useQuery({
    queryKey: ['company-audit', companyId, filters],
    queryFn: () =>
      listCompanyAuditLogs({
        company_id: companyId!,
        action: filters.action,
        resource_type: filters.resource_type,
        limit: 100,
      }),
    enabled: Boolean(companyId),
  })
}

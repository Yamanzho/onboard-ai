import type { OnboardingAnalytics } from '../types/analytics'
import { apiRequest } from './apiClient'

export async function getOnboardingAnalytics(
  companyId: string,
): Promise<OnboardingAnalytics> {
  const search = new URLSearchParams({ company_id: companyId })
  return apiRequest<OnboardingAnalytics>(
    `/api/v1/analytics/onboarding?${search}`,
  )
}

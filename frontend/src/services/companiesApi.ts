import type { Company } from '../types/company'
import { apiRequest } from './apiClient'

export async function getCompany(companyId: string): Promise<Company> {
  return apiRequest<Company>(`/api/v1/companies/${companyId}`)
}

export async function updateCompany(
  companyId: string,
  payload: { name?: string; timezone?: string },
): Promise<Company> {
  return apiRequest<Company>(`/api/v1/companies/${companyId}`, {
    method: 'PATCH',
    body: payload,
  })
}

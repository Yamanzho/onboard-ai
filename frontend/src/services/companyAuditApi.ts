import type { CompanyAuditLogListResponse } from '../types/analytics'
import { apiRequest } from './apiClient'

export async function listCompanyAuditLogs(params: {
  company_id: string
  action?: string
  resource_type?: string
  offset?: number
  limit?: number
}): Promise<CompanyAuditLogListResponse> {
  const search = new URLSearchParams({ company_id: params.company_id })
  if (params.action) search.set('action', params.action)
  if (params.resource_type) search.set('resource_type', params.resource_type)
  if (params.offset !== undefined) search.set('offset', String(params.offset))
  if (params.limit !== undefined) search.set('limit', String(params.limit))
  return apiRequest<CompanyAuditLogListResponse>(`/api/v1/audit-logs?${search}`)
}

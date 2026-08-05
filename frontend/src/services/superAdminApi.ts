import type { TokenResponse } from '../types/auth'
import type {
  CompanyLimits,
  CompanySubscription,
  CompanySubscriptionUpdate,
  CompanyUserCreate,
  PlatformAuditLog,
  PlatformCompany,
  PlatformCompanyCreate,
  PlatformCompanyDetail,
  PlatformCompanyProfileUpdate,
  PlatformCompanyUpdate,
  PlatformDashboardStats,
  PlatformSettings,
  PlatformUser,
  PlatformUserUpdate,
  SubscriptionHistoryEvent,
  SuperAdminUser,
} from '../types/superAdmin'
import { superAdminRequest } from './superAdminApiClient'

export async function login(
  email: string,
  password: string,
): Promise<TokenResponse> {
  return superAdminRequest<TokenResponse>('/api/v1/super-admin/auth/login', {
    method: 'POST',
    auth: false,
    body: { email, password },
  })
}

export async function fetchMe(): Promise<SuperAdminUser> {
  return superAdminRequest<SuperAdminUser>('/api/v1/super-admin/auth/me')
}

export async function fetchDashboard(): Promise<PlatformDashboardStats> {
  return superAdminRequest<PlatformDashboardStats>(
    '/api/v1/super-admin/dashboard',
  )
}

export async function listCompanies(params?: {
  is_active?: boolean
}): Promise<PlatformCompany[]> {
  const search = new URLSearchParams()
  if (params?.is_active !== undefined) {
    search.set('is_active', String(params.is_active))
  }
  const qs = search.toString()
  return superAdminRequest<PlatformCompany[]>(
    `/api/v1/super-admin/companies${qs ? `?${qs}` : ''}`,
  )
}

export async function getCompany(
  companyId: string,
): Promise<PlatformCompanyDetail> {
  return superAdminRequest<PlatformCompanyDetail>(
    `/api/v1/super-admin/companies/${companyId}`,
  )
}

export async function createCompany(
  payload: PlatformCompanyCreate,
): Promise<PlatformCompanyDetail> {
  return superAdminRequest<PlatformCompanyDetail>(
    '/api/v1/super-admin/companies',
    { method: 'POST', body: payload },
  )
}

export async function updateCompany(
  companyId: string,
  payload: PlatformCompanyUpdate,
): Promise<PlatformCompany> {
  return superAdminRequest<PlatformCompany>(
    `/api/v1/super-admin/companies/${companyId}`,
    { method: 'PATCH', body: payload },
  )
}

export async function updateCompanyProfile(
  companyId: string,
  payload: PlatformCompanyProfileUpdate,
): Promise<PlatformCompanyDetail> {
  return superAdminRequest<PlatformCompanyDetail>(
    `/api/v1/super-admin/companies/${companyId}/profile`,
    { method: 'PATCH', body: payload },
  )
}

export async function activateCompany(
  companyId: string,
): Promise<PlatformCompany> {
  return superAdminRequest<PlatformCompany>(
    `/api/v1/super-admin/companies/${companyId}/activate`,
    { method: 'POST' },
  )
}

export async function deactivateCompany(
  companyId: string,
): Promise<PlatformCompany> {
  return superAdminRequest<PlatformCompany>(
    `/api/v1/super-admin/companies/${companyId}/deactivate`,
    { method: 'POST' },
  )
}

export async function getCompanySubscription(
  companyId: string,
): Promise<CompanySubscription> {
  return superAdminRequest<CompanySubscription>(
    `/api/v1/super-admin/companies/${companyId}/subscription`,
  )
}

export async function updateCompanySubscription(
  companyId: string,
  payload: CompanySubscriptionUpdate,
): Promise<CompanySubscription> {
  return superAdminRequest<CompanySubscription>(
    `/api/v1/super-admin/companies/${companyId}/subscription`,
    { method: 'PATCH', body: payload },
  )
}

export async function listSubscriptionHistory(
  companyId: string,
): Promise<SubscriptionHistoryEvent[]> {
  return superAdminRequest<SubscriptionHistoryEvent[]>(
    `/api/v1/super-admin/companies/${companyId}/subscription/history`,
  )
}

export async function listCompanySubscriptions(
  companyId: string,
): Promise<CompanySubscription[]> {
  return superAdminRequest<CompanySubscription[]>(
    `/api/v1/super-admin/companies/${companyId}/subscriptions`,
  )
}

export async function getCompanyLimits(
  companyId: string,
): Promise<CompanyLimits> {
  return superAdminRequest<CompanyLimits>(
    `/api/v1/super-admin/companies/${companyId}/limits`,
  )
}

export async function listCompanyUsers(
  companyId: string,
  params?: { role?: string; status?: string },
): Promise<PlatformUser[]> {
  const search = new URLSearchParams()
  if (params?.role) search.set('role', params.role)
  if (params?.status) search.set('status', params.status)
  const qs = search.toString()
  return superAdminRequest<PlatformUser[]>(
    `/api/v1/super-admin/companies/${companyId}/users${qs ? `?${qs}` : ''}`,
  )
}

export async function createCompanyUser(
  companyId: string,
  payload: CompanyUserCreate,
): Promise<PlatformUser> {
  return superAdminRequest<PlatformUser>(
    `/api/v1/super-admin/companies/${companyId}/users`,
    { method: 'POST', body: payload },
  )
}

export async function listUsers(params?: {
  company_id?: string
  role?: string
  status?: string
}): Promise<PlatformUser[]> {
  const search = new URLSearchParams()
  if (params?.company_id) search.set('company_id', params.company_id)
  if (params?.role) search.set('role', params.role)
  if (params?.status) search.set('status', params.status)
  const qs = search.toString()
  return superAdminRequest<PlatformUser[]>(
    `/api/v1/super-admin/users${qs ? `?${qs}` : ''}`,
  )
}

export async function updateUser(
  employeeId: string,
  payload: PlatformUserUpdate,
): Promise<PlatformUser> {
  return superAdminRequest<PlatformUser>(
    `/api/v1/super-admin/users/${employeeId}`,
    { method: 'PATCH', body: payload },
  )
}

export async function blockUser(employeeId: string): Promise<PlatformUser> {
  return superAdminRequest<PlatformUser>(
    `/api/v1/super-admin/users/${employeeId}/block`,
    { method: 'POST' },
  )
}

export async function resendUserInvite(employeeId: string): Promise<void> {
  await superAdminRequest<void>(
    `/api/v1/super-admin/users/${employeeId}/resend-invite`,
    { method: 'POST' },
  )
}

export async function listAuditLogs(params?: {
  company_id?: string
}): Promise<PlatformAuditLog[]> {
  const search = new URLSearchParams()
  if (params?.company_id) search.set('company_id', params.company_id)
  const qs = search.toString()
  return superAdminRequest<PlatformAuditLog[]>(
    `/api/v1/super-admin/audit-logs${qs ? `?${qs}` : ''}`,
  )
}

export async function fetchSettings(): Promise<PlatformSettings> {
  return superAdminRequest<PlatformSettings>('/api/v1/super-admin/settings')
}

export async function updateSettings(
  payload: Partial<PlatformSettings>,
): Promise<PlatformSettings> {
  return superAdminRequest<PlatformSettings>('/api/v1/super-admin/settings', {
    method: 'PATCH',
    body: payload,
  })
}

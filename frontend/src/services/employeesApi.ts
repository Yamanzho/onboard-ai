import type {
  Employee,
  EmployeeCreate,
  EmployeeInviteHistoryResponse,
  EmployeeListParams,
  EmployeeUpdate,
} from '../types/employee'
import { apiRequest } from './apiClient'

export async function listEmployees(
  params: EmployeeListParams,
): Promise<Employee[]> {
  const search = new URLSearchParams()
  search.set('company_id', params.company_id)
  if (params.status) search.set('status', params.status)
  if (params.department_id) search.set('department_id', params.department_id)
  if (params.offset !== undefined) search.set('offset', String(params.offset))
  if (params.limit !== undefined) search.set('limit', String(params.limit))
  return apiRequest<Employee[]>(`/api/v1/employees?${search}`)
}

export async function getEmployee(employeeId: string): Promise<Employee> {
  return apiRequest<Employee>(`/api/v1/employees/${employeeId}`)
}

export async function createEmployee(payload: EmployeeCreate): Promise<Employee> {
  const body: Record<string, unknown> = {
    company_id: payload.company_id,
    full_name: payload.full_name,
    email: payload.email ?? null,
    role: payload.role,
    status: payload.status,
  }
  if (payload.telegram_user_id !== undefined) {
    body.telegram_user_id = payload.telegram_user_id
  }
  if (payload.telegram_chat_id !== undefined) {
    body.telegram_chat_id = payload.telegram_chat_id
  }
  if (payload.telegram_username !== undefined) {
    body.telegram_username = payload.telegram_username
  }
  if (payload.hired_at !== undefined) {
    body.hired_at = payload.hired_at
  }
  if (payload.department_id !== undefined) {
    body.department_id = payload.department_id
  }
  if (payload.manager_id !== undefined) {
    body.manager_id = payload.manager_id
  }
  if (payload.job_title !== undefined) {
    body.job_title = payload.job_title
  }
  return apiRequest<Employee>('/api/v1/employees', {
    method: 'POST',
    body,
  })
}

export async function updateEmployee(
  employeeId: string,
  payload: EmployeeUpdate,
): Promise<Employee> {
  return apiRequest<Employee>(`/api/v1/employees/${employeeId}`, {
    method: 'PATCH',
    body: payload,
  })
}

export async function deleteEmployee(employeeId: string): Promise<void> {
  return apiRequest<void>(`/api/v1/employees/${employeeId}`, {
    method: 'DELETE',
  })
}

export async function initiatePasswordReset(
  employeeId: string,
): Promise<import('../types/auth').PasswordResetInitiateResult> {
  return apiRequest(`/api/v1/employees/${employeeId}/password/reset`, {
    method: 'POST',
    body: {},
  })
}

export async function resendInvite(employeeId: string): Promise<Employee> {
  return apiRequest<Employee>(`/api/v1/employees/${employeeId}/resend-invite`, {
    method: 'POST',
    body: {},
  })
}

export async function listInvites(
  employeeId: string,
): Promise<EmployeeInviteHistoryResponse> {
  return apiRequest<EmployeeInviteHistoryResponse>(
    `/api/v1/employees/${employeeId}/invites`,
  )
}

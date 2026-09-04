import type {
  Assignment,
  AssignmentBulkCreateResult,
  AssignmentCreate,
  AssignmentListParams,
  AssignmentProgress,
  ProgressItem,
} from '../types/assignment'
import { apiRequest } from './apiClient'

function isBulkResult(
  value: Assignment | AssignmentBulkCreateResult,
): value is AssignmentBulkCreateResult {
  return 'items' in value && Array.isArray(value.items)
}

export async function listAssignments(
  params: AssignmentListParams,
): Promise<Assignment[]> {
  const search = new URLSearchParams()
  search.set('company_id', params.company_id)
  if (params.status) search.set('status', params.status)
  if (params.employee_id) search.set('employee_id', params.employee_id)
  if (params.offset !== undefined) search.set('offset', String(params.offset))
  if (params.limit !== undefined) search.set('limit', String(params.limit))
  return apiRequest<Assignment[]>(`/api/v1/assignments?${search}`)
}

export async function listEmployeeAssignments(
  employeeId: string,
  params: { status?: string; offset?: number; limit?: number } = {},
): Promise<Assignment[]> {
  const search = new URLSearchParams()
  if (params.status) search.set('status', params.status)
  if (params.offset !== undefined) search.set('offset', String(params.offset))
  if (params.limit !== undefined) search.set('limit', String(params.limit))
  const qs = search.toString()
  return apiRequest<Assignment[]>(
    `/api/v1/employees/${employeeId}/assignments${qs ? `?${qs}` : ''}`,
  )
}

export async function getAssignment(assignmentId: string): Promise<Assignment> {
  return apiRequest<Assignment>(`/api/v1/assignments/${assignmentId}`)
}

export async function createAssignment(
  payload: AssignmentCreate,
): Promise<Assignment[]> {
  const result = await apiRequest<Assignment | AssignmentBulkCreateResult>(
    '/api/v1/assignments',
    {
      method: 'POST',
      body: payload,
    },
  )
  if (isBulkResult(result)) return result.items
  return [result]
}

export async function cancelAssignment(assignmentId: string): Promise<void> {
  return apiRequest<void>(`/api/v1/assignments/${assignmentId}`, {
    method: 'DELETE',
  })
}

export async function getAssignmentProgress(
  assignmentId: string,
): Promise<AssignmentProgress> {
  return apiRequest<AssignmentProgress>(
    `/api/v1/assignments/${assignmentId}/progress`,
  )
}

export async function completeProgress(
  progressId: string,
  payload?: Record<string, unknown>,
): Promise<ProgressItem> {
  return apiRequest<ProgressItem>(`/api/v1/progress/${progressId}/complete`, {
    method: 'POST',
    body: { payload: payload ?? {} },
  })
}

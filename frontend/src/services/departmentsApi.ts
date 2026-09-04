import type {
  Department,
  DepartmentCreate,
  DepartmentUpdate,
} from '../types/department'
import { apiRequest } from './apiClient'

export async function listDepartments(
  companyId: string,
  isActive?: boolean,
): Promise<Department[]> {
  const params = new URLSearchParams({ company_id: companyId })
  if (isActive !== undefined) params.set('is_active', String(isActive))
  return apiRequest<Department[]>(`/api/v1/departments?${params}`)
}

export async function createDepartment(
  payload: DepartmentCreate,
): Promise<Department> {
  return apiRequest<Department>('/api/v1/departments', {
    method: 'POST',
    body: payload,
  })
}

export async function updateDepartment(
  departmentId: string,
  payload: DepartmentUpdate,
): Promise<Department> {
  return apiRequest<Department>(`/api/v1/departments/${departmentId}`, {
    method: 'PATCH',
    body: payload,
  })
}

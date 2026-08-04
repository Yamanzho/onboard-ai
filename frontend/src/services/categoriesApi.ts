import type { Category, CategoryCreate, CategoryUpdate } from '../types/category'
import { apiRequest } from './apiClient'

export async function listCategories(companyId: string): Promise<Category[]> {
  const params = new URLSearchParams({ company_id: companyId })
  return apiRequest<Category[]>(`/api/v1/knowledge/categories?${params}`)
}

export async function createCategory(payload: CategoryCreate): Promise<Category> {
  return apiRequest<Category>('/api/v1/knowledge/categories', {
    method: 'POST',
    body: payload,
  })
}

export async function updateCategory(
  categoryId: string,
  payload: CategoryUpdate,
): Promise<Category> {
  return apiRequest<Category>(`/api/v1/knowledge/categories/${categoryId}`, {
    method: 'PATCH',
    body: payload,
  })
}

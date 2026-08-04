import type { Tag, TagCreate, TagUpdate } from '../types/tag'
import { apiRequest } from './apiClient'

export async function listTags(companyId: string): Promise<Tag[]> {
  const params = new URLSearchParams({ company_id: companyId })
  return apiRequest<Tag[]>(`/api/v1/knowledge/tags?${params}`)
}

export async function createTag(payload: TagCreate): Promise<Tag> {
  return apiRequest<Tag>('/api/v1/knowledge/tags', {
    method: 'POST',
    body: payload,
  })
}

export async function updateTag(tagId: string, payload: TagUpdate): Promise<Tag> {
  return apiRequest<Tag>(`/api/v1/knowledge/tags/${tagId}`, {
    method: 'PATCH',
    body: payload,
  })
}

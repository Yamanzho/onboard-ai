import type {
  QuestionTopic,
  QuestionTopicCreate,
  QuestionTopicUpdate,
  TopicResponsibilityPayload,
} from '../types/topic'
import { apiRequest } from './apiClient'

export async function listTopics(
  companyId: string,
  isActive?: boolean,
): Promise<QuestionTopic[]> {
  const params = new URLSearchParams({ company_id: companyId })
  if (isActive !== undefined) params.set('is_active', String(isActive))
  return apiRequest<QuestionTopic[]>(`/api/v1/topics?${params}`)
}

export async function createTopic(
  payload: QuestionTopicCreate,
): Promise<QuestionTopic> {
  return apiRequest<QuestionTopic>('/api/v1/topics', {
    method: 'POST',
    body: payload,
  })
}

export async function updateTopic(
  topicId: string,
  payload: QuestionTopicUpdate,
): Promise<QuestionTopic> {
  return apiRequest<QuestionTopic>(`/api/v1/topics/${topicId}`, {
    method: 'PATCH',
    body: payload,
  })
}

export async function setTopicResponsibility(
  topicId: string,
  payload: TopicResponsibilityPayload,
): Promise<QuestionTopic> {
  return apiRequest<QuestionTopic>(`/api/v1/topics/${topicId}/responsibility`, {
    method: 'PUT',
    body: payload,
  })
}

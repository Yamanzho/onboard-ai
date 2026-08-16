import {
  AI_CHAT_CLIENT_TIMEOUT_MS,
  type AIChatRequest,
  type AIChatResponse,
  type AIConversationDetail,
  type AIConversationListResponse,
} from '../types/ai'
import { apiRequest } from './apiClient'

/**
 * Employee AI chat. Identity comes from the authenticated session cookies.
 * Request body is message plus optional conversation continuation token only.
 */
export async function postAIChat(
  message: string,
  conversationId?: string,
): Promise<AIChatResponse> {
  const body: AIChatRequest = conversationId
    ? { message, conversation_id: conversationId }
    : { message }

  return apiRequest<AIChatResponse>('/api/v1/ai/chat', {
    method: 'POST',
    body,
    signal: AbortSignal.timeout(AI_CHAT_CLIENT_TIMEOUT_MS),
  })
}

export async function listAIConversations(): Promise<AIConversationListResponse> {
  return apiRequest<AIConversationListResponse>('/api/v1/ai/conversations')
}

export async function getAIConversation(
  conversationId: string,
): Promise<AIConversationDetail> {
  return apiRequest<AIConversationDetail>(
    `/api/v1/ai/conversations/${conversationId}`,
  )
}

export async function deleteAIConversation(conversationId: string): Promise<void> {
  await apiRequest<void>(`/api/v1/ai/conversations/${conversationId}`, {
    method: 'DELETE',
  })
}

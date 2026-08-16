/** Matches backend MAX_CHAT_QUESTION_CHARS. Backend remains the authority. */
export const MAX_CHAT_QUESTION_CHARS = 2000

/** Client abort slightly above backend AI_CHAT_TIMEOUT_SECONDS (25s). */
export const AI_CHAT_CLIENT_TIMEOUT_MS = 35_000

export interface AIChatRequest {
  message: string
  conversation_id?: string
}

export interface AIChatCitation {
  source_id: string
  title: string
  article_id: string
}

export interface AIChatResponse {
  answer: string
  no_answer: boolean
  conversation_id: string
  citations: AIChatCitation[]
}

export interface ChatMessage {
  id: string
  role: 'user' | 'assistant'
  content: string
  citations?: AIChatCitation[]
  noAnswer?: boolean
}

export interface AIConversationSummary {
  conversation_id: string
  title: string | null
  created_at: string
  updated_at: string
  last_message_preview: string | null
  message_count: number
}

export interface AIConversationListResponse {
  items: AIConversationSummary[]
}

export interface AIConversationMessage {
  message_id: string
  role: 'user' | 'assistant'
  content: string
  created_at: string
  citations: AIChatCitation[]
  no_answer: boolean
}

export interface AIConversationDetail {
  conversation_id: string
  title: string | null
  created_at: string
  updated_at: string
  messages: AIConversationMessage[]
}

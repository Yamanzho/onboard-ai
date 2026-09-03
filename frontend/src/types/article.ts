import type { Tag } from './tag'

export type KnowledgeStatus = 'draft' | 'published' | 'archived'
export type KnowledgeVisibility = 'company' | 'program'
export type KnowledgeBodyFormat = 'markdown' | 'html' | 'plain'
export type KnowledgeIndexStatus = 'pending' | 'indexing' | 'indexed' | 'failed'
export type EmbeddingIncompatibilityReason =
  | 'provider_changed'
  | 'model_changed'
  | 'dimension_changed'
  | 'metadata_missing'
  | 'not_indexed'

export interface ArticleVersion {
  id: string
  article_id: string
  version: number
  title: string
  body: string
  body_format: string
  change_summary: string | null
  created_by_id: string | null
  published_at: string | null
  index_status: KnowledgeIndexStatus
  embedding_provider: string | null
  embedding_model: string | null
  embedding_dimension: number | null
  indexed_chunk_count: number | null
  indexing_started_at: string | null
  indexed_at: string | null
  indexing_failed_at: string | null
  failure_category: string | null
  indexing_in_progress: boolean
  index_stale: boolean
  embedding_compatible: boolean
  reindex_required: boolean
  embedding_incompatibility_reason: EmbeddingIncompatibilityReason | null
  created_at: string
  updated_at: string
}

export interface Article {
  id: string
  company_id: string
  category_id: string | null
  current_version_id: string | null
  status: KnowledgeStatus | string
  visibility: KnowledgeVisibility | string
  created_by_id: string | null
  current_version: ArticleVersion | null
  tags: Tag[]
  program_ids?: string[]
  created_at: string
  updated_at: string
}

export interface ArticleVersionSummary {
  id: string
  article_id: string
  version: number
  title: string
  change_summary: string | null
  created_by_id: string | null
  published_at: string | null
  index_status: KnowledgeIndexStatus
  embedding_provider: string | null
  embedding_model: string | null
  embedding_dimension: number | null
  indexed_chunk_count: number | null
  indexing_started_at: string | null
  indexed_at: string | null
  indexing_failed_at: string | null
  failure_category: string | null
  indexing_in_progress: boolean
  index_stale: boolean
  embedding_compatible: boolean
  reindex_required: boolean
  embedding_incompatibility_reason: EmbeddingIncompatibilityReason | null
  created_at: string
}

export interface ArticleVersionListResponse {
  items: ArticleVersionSummary[]
}

export interface ArticleListResponse {
  items: Article[]
}

export interface ArticleCreate {
  company_id: string
  title: string
  body: string
  body_format?: KnowledgeBodyFormat
  category_id?: string | null
  visibility?: KnowledgeVisibility
  tag_ids?: string[]
  change_summary?: string | null
  program_ids?: string[]
}

export interface ArticleUpdate {
  title?: string
  body?: string
  body_format?: KnowledgeBodyFormat
  category_id?: string | null
  visibility?: KnowledgeVisibility
  tag_ids?: string[]
  change_summary?: string | null
  program_ids?: string[]
}

export interface ArticleListParams {
  company_id: string
  status?: string
  category_id?: string
  tag_id?: string
  q?: string
  offset?: number
  limit?: number
}

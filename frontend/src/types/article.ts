import type { Tag } from './tag'

export type KnowledgeStatus = 'draft' | 'published' | 'archived'
export type KnowledgeVisibility = 'company' | 'program'
export type KnowledgeBodyFormat = 'markdown' | 'html' | 'plain'

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
  created_at: string
  updated_at: string
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
}

export interface ArticleUpdate {
  title?: string
  body?: string
  body_format?: KnowledgeBodyFormat
  category_id?: string | null
  visibility?: KnowledgeVisibility
  tag_ids?: string[]
  change_summary?: string | null
}

export interface ArticleListParams {
  company_id: string
  status?: string
  category_id?: string
  tag_id?: string
  offset?: number
  limit?: number
}

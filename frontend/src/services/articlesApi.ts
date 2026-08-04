import type {
  Article,
  ArticleCreate,
  ArticleListParams,
  ArticleListResponse,
  ArticleUpdate,
} from '../types/article'
import { apiRequest } from './apiClient'

export async function listArticles(
  params: ArticleListParams,
): Promise<ArticleListResponse> {
  const search = new URLSearchParams()
  search.set('company_id', params.company_id)
  if (params.status) search.set('status', params.status)
  if (params.category_id) search.set('category_id', params.category_id)
  if (params.tag_id) search.set('tag_id', params.tag_id)
  if (params.offset !== undefined) search.set('offset', String(params.offset))
  if (params.limit !== undefined) search.set('limit', String(params.limit))
  return apiRequest<ArticleListResponse>(`/api/v1/knowledge/articles?${search}`)
}

export async function getArticle(articleId: string): Promise<Article> {
  return apiRequest<Article>(`/api/v1/knowledge/articles/${articleId}`)
}

export async function createArticle(payload: ArticleCreate): Promise<Article> {
  return apiRequest<Article>('/api/v1/knowledge/articles', {
    method: 'POST',
    body: payload,
  })
}

export async function updateArticle(
  articleId: string,
  payload: ArticleUpdate,
): Promise<Article> {
  return apiRequest<Article>(`/api/v1/knowledge/articles/${articleId}`, {
    method: 'PUT',
    body: payload,
  })
}

export async function publishArticle(articleId: string): Promise<Article> {
  return apiRequest<Article>(`/api/v1/knowledge/articles/${articleId}/publish`, {
    method: 'POST',
  })
}

export async function archiveArticle(articleId: string): Promise<Article> {
  return apiRequest<Article>(`/api/v1/knowledge/articles/${articleId}/archive`, {
    method: 'POST',
  })
}

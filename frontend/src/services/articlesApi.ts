import type {
  Article,
  ArticleCreate,
  ArticleListParams,
  ArticleListResponse,
  ArticleUpdate,
  ArticleVersion,
  ArticleVersionListResponse,
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
  if (params.q) search.set('q', params.q)
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

export async function listArticleVersions(
  articleId: string,
): Promise<ArticleVersionListResponse> {
  return apiRequest<ArticleVersionListResponse>(
    `/api/v1/knowledge/articles/${articleId}/versions`,
  )
}

export async function getArticleVersion(
  articleId: string,
  version: number,
): Promise<ArticleVersion> {
  return apiRequest<ArticleVersion>(
    `/api/v1/knowledge/articles/${articleId}/versions/${version}`,
  )
}

export async function restoreArticleVersion(
  articleId: string,
  version: number,
): Promise<Article> {
  return apiRequest<Article>(
    `/api/v1/knowledge/articles/${articleId}/versions/${version}/restore`,
    { method: 'POST' },
  )
}

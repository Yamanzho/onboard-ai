import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import * as articlesApi from '../services/articlesApi'
import type { ArticleCreate, ArticleListParams, ArticleUpdate } from '../types/article'
import { useAuth } from './useAuth'

export function useArticles(filters: Omit<ArticleListParams, 'company_id'> = {}) {
  const { user } = useAuth()
  const companyId = user?.company_id

  return useQuery({
    queryKey: ['articles', companyId, filters],
    queryFn: () =>
      articlesApi.listArticles({
        company_id: companyId!,
        ...filters,
      }),
    enabled: Boolean(companyId),
  })
}

export function useArticle(articleId: string | undefined) {
  return useQuery({
    queryKey: ['article', articleId],
    queryFn: () => articlesApi.getArticle(articleId!),
    enabled: Boolean(articleId),
  })
}

export function useArticleMutations() {
  const qc = useQueryClient()
  const { user } = useAuth()

  const invalidate = () => {
    void qc.invalidateQueries({ queryKey: ['articles'] })
    void qc.invalidateQueries({ queryKey: ['article'] })
  }

  const create = useMutation({
    mutationFn: (payload: Omit<ArticleCreate, 'company_id'> & { company_id?: string }) =>
      articlesApi.createArticle({
        ...payload,
        company_id: payload.company_id ?? user!.company_id,
      }),
    onSuccess: invalidate,
  })

  const update = useMutation({
    mutationFn: ({ id, payload }: { id: string; payload: ArticleUpdate }) =>
      articlesApi.updateArticle(id, payload),
    onSuccess: invalidate,
  })

  const publish = useMutation({
    mutationFn: (id: string) => articlesApi.publishArticle(id),
    onSuccess: invalidate,
  })

  const archive = useMutation({
    mutationFn: (id: string) => articlesApi.archiveArticle(id),
    onSuccess: invalidate,
  })

  return { create, update, publish, archive }
}

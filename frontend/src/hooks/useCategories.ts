import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import * as categoriesApi from '../services/categoriesApi'
import type { CategoryCreate, CategoryUpdate } from '../types/category'
import { useAuth } from './useAuth'

export function useCategories() {
  const { user } = useAuth()
  const companyId = user?.company_id

  return useQuery({
    queryKey: ['categories', companyId],
    queryFn: () => categoriesApi.listCategories(companyId!),
    enabled: Boolean(companyId),
  })
}

export function useCategoryMutations() {
  const qc = useQueryClient()
  const { user } = useAuth()

  const create = useMutation({
    mutationFn: (payload: Omit<CategoryCreate, 'company_id'> & { company_id?: string }) =>
      categoriesApi.createCategory({
        ...payload,
        company_id: payload.company_id ?? user!.company_id,
      }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['categories'] })
    },
  })

  const update = useMutation({
    mutationFn: ({ id, payload }: { id: string; payload: CategoryUpdate }) =>
      categoriesApi.updateCategory(id, payload),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['categories'] })
    },
  })

  return { create, update }
}

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import * as tagsApi from '../services/tagsApi'
import type { TagCreate, TagUpdate } from '../types/tag'
import { useAuth } from './useAuth'

export function useTags() {
  const { user } = useAuth()
  const companyId = user?.company_id

  return useQuery({
    queryKey: ['tags', companyId],
    queryFn: () => tagsApi.listTags(companyId!),
    enabled: Boolean(companyId),
  })
}

export function useTagMutations() {
  const qc = useQueryClient()
  const { user } = useAuth()

  const create = useMutation({
    mutationFn: (payload: Omit<TagCreate, 'company_id'> & { company_id?: string }) =>
      tagsApi.createTag({
        ...payload,
        company_id: payload.company_id ?? user!.company_id,
      }),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['tags'] })
    },
  })

  const update = useMutation({
    mutationFn: ({ id, payload }: { id: string; payload: TagUpdate }) =>
      tagsApi.updateTag(id, payload),
    onSuccess: () => {
      void qc.invalidateQueries({ queryKey: ['tags'] })
    },
  })

  return { create, update }
}

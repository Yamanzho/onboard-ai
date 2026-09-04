import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import * as topicsApi from '../services/topicsApi'
import type {
  QuestionTopicCreate,
  QuestionTopicUpdate,
  TopicResponsibilityPayload,
} from '../types/topic'
import { useAuth } from './useAuth'

export function useTopics(isActive?: boolean) {
  const { user } = useAuth()
  const companyId = user?.company_id

  return useQuery({
    queryKey: ['topics', companyId, isActive],
    queryFn: () => topicsApi.listTopics(companyId!, isActive),
    enabled: Boolean(companyId),
  })
}

export function useTopicMutations() {
  const qc = useQueryClient()
  const { user } = useAuth()

  const invalidate = () => {
    void qc.invalidateQueries({ queryKey: ['topics'] })
  }

  const create = useMutation({
    mutationFn: (
      payload: Omit<QuestionTopicCreate, 'company_id'> & { company_id?: string },
    ) =>
      topicsApi.createTopic({
        ...payload,
        company_id: payload.company_id ?? user!.company_id,
      }),
    onSuccess: invalidate,
  })

  const update = useMutation({
    mutationFn: ({ id, payload }: { id: string; payload: QuestionTopicUpdate }) =>
      topicsApi.updateTopic(id, payload),
    onSuccess: invalidate,
  })

  const setResponsibility = useMutation({
    mutationFn: ({
      id,
      payload,
    }: {
      id: string
      payload: TopicResponsibilityPayload
    }) => topicsApi.setTopicResponsibility(id, payload),
    onSuccess: invalidate,
  })

  return { create, update, setResponsibility }
}

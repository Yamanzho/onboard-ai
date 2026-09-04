import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import * as assignmentsApi from '../services/assignmentsApi'
import type {
  Assignment,
  AssignmentCreate,
  AssignmentListParams,
} from '../types/assignment'
import { useAuth } from './useAuth'

const LIST_LIMIT = 1000

export function useAssignments(
  filters: Omit<AssignmentListParams, 'company_id' | 'offset' | 'limit'> = {},
) {
  const { user } = useAuth()
  const companyId = user?.company_id

  return useQuery({
    queryKey: ['assignments', companyId, filters],
    queryFn: () =>
      assignmentsApi.listAssignments({
        company_id: companyId!,
        status: filters.status,
        employee_id: filters.employee_id,
        offset: 0,
        limit: LIST_LIMIT,
      }),
    enabled: Boolean(companyId),
  })
}

export function useEmployeeAssignments(employeeId: string | undefined) {
  return useQuery({
    queryKey: ['employee-assignments', employeeId],
    queryFn: () =>
      assignmentsApi.listEmployeeAssignments(employeeId!, { limit: LIST_LIMIT }),
    enabled: Boolean(employeeId),
  })
}

export function useAssignment(assignmentId: string | undefined) {
  return useQuery({
    queryKey: ['assignment', assignmentId],
    queryFn: () => assignmentsApi.getAssignment(assignmentId!),
    enabled: Boolean(assignmentId),
  })
}

export function useAssignmentProgress(assignmentId: string | undefined) {
  return useQuery({
    queryKey: ['assignment-progress', assignmentId],
    queryFn: () => assignmentsApi.getAssignmentProgress(assignmentId!),
    enabled: Boolean(assignmentId),
  })
}

export function useAssignmentNotifications(assignmentId: string | undefined) {
  return useQuery({
    queryKey: ['assignment-notifications', assignmentId],
    queryFn: () => assignmentsApi.getAssignmentNotifications(assignmentId!),
    enabled: Boolean(assignmentId),
  })
}

export function useAssignmentAcknowledgements(assignmentId: string | undefined) {
  return useQuery({
    queryKey: ['assignment-acknowledgements', assignmentId],
    queryFn: () => assignmentsApi.listAcknowledgements(assignmentId!),
    enabled: Boolean(assignmentId),
  })
}

function invalidateAssignmentCaches(qc: ReturnType<typeof useQueryClient>) {
  void qc.invalidateQueries({ queryKey: ['assignments'] })
  void qc.invalidateQueries({ queryKey: ['assignment'] })
  void qc.invalidateQueries({ queryKey: ['assignment-progress'] })
  void qc.invalidateQueries({ queryKey: ['assignment-notifications'] })
  void qc.invalidateQueries({ queryKey: ['employee-assignments'] })
  void qc.invalidateQueries({ queryKey: ['assignment-acknowledgements'] })
}

export function useAssignmentMutations() {
  const qc = useQueryClient()
  const { user } = useAuth()

  const create = useMutation({
    mutationFn: (payload: AssignmentCreate) =>
      assignmentsApi.createAssignment({
        ...payload,
        assigned_by_id: payload.assigned_by_id ?? user?.id ?? null,
      }),
    onSuccess: invalidateAssignmentCaches.bind(null, qc),
  })

  const cancel = useMutation({
    mutationFn: (id: string) => assignmentsApi.cancelAssignment(id),
    onMutate: async (id) => {
      await qc.cancelQueries({ queryKey: ['assignments'] })
      await qc.cancelQueries({ queryKey: ['assignment', id] })
      const previousLists = qc.getQueriesData<Assignment[]>({
        queryKey: ['assignments'],
      })
      const previousEmployeeLists = qc.getQueriesData<Assignment[]>({
        queryKey: ['employee-assignments'],
      })
      const previous = qc.getQueryData<Assignment>(['assignment', id])

      const markCancelled = (old: Assignment[] | undefined) =>
        old
          ? old.map((a) =>
              a.id === id ? { ...a, status: 'cancelled' as const } : a,
            )
          : old

      qc.setQueriesData<Assignment[]>({ queryKey: ['assignments'] }, markCancelled)
      qc.setQueriesData<Assignment[]>(
        { queryKey: ['employee-assignments'] },
        markCancelled,
      )
      if (previous) {
        qc.setQueryData(['assignment', id], {
          ...previous,
          status: 'cancelled',
        })
      }
      return { previousLists, previousEmployeeLists, previous }
    },
    onError: (_err, id, context) => {
      if (!context) return
      for (const [key, data] of context.previousLists) {
        qc.setQueryData(key, data)
      }
      for (const [key, data] of context.previousEmployeeLists) {
        qc.setQueryData(key, data)
      }
      if (context.previous) {
        qc.setQueryData(['assignment', id], context.previous)
      }
    },
    onSettled: () => invalidateAssignmentCaches(qc),
  })

  const remindNow = useMutation({
    mutationFn: (id: string) => assignmentsApi.remindNow(id),
    onSuccess: invalidateAssignmentCaches.bind(null, qc),
  })

  const acknowledge = useMutation({
    mutationFn: ({
      assignmentId,
      itemId,
    }: {
      assignmentId: string
      itemId: string
    }) => assignmentsApi.acknowledgeDocument(assignmentId, itemId),
    onSuccess: invalidateAssignmentCaches.bind(null, qc),
  })

  return { create, cancel, remindNow, acknowledge }
}

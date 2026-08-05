import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import * as programsApi from '../services/programsApi'
import type {
  Program,
  ProgramCreate,
  ProgramListParams,
  ProgramUpdate,
} from '../types/program'
import type { Step, StepCreate, StepUpdate } from '../types/step'
import { useAuth } from './useAuth'

const LIST_LIMIT = 1000

export function usePrograms(
  filters: Omit<ProgramListParams, 'company_id' | 'offset' | 'limit'> = {},
) {
  const { user } = useAuth()
  const companyId = user?.company_id

  return useQuery({
    queryKey: ['programs', companyId, filters],
    queryFn: () =>
      programsApi.listPrograms({
        company_id: companyId!,
        is_active: filters.is_active,
        offset: 0,
        limit: LIST_LIMIT,
      }),
    enabled: Boolean(companyId),
  })
}

export function useProgram(programId: string | undefined) {
  return useQuery({
    queryKey: ['program', programId],
    queryFn: () => programsApi.getProgram(programId!),
    enabled: Boolean(programId),
  })
}

export function useProgramSteps(programId: string | undefined) {
  return useQuery({
    queryKey: ['program-steps', programId],
    queryFn: () => programsApi.listProgramSteps(programId!),
    enabled: Boolean(programId),
  })
}

function invalidateProgramCaches(
  qc: ReturnType<typeof useQueryClient>,
  programId?: string,
) {
  void qc.invalidateQueries({ queryKey: ['programs'] })
  void qc.invalidateQueries({ queryKey: ['program'] })
  if (programId) {
    void qc.invalidateQueries({ queryKey: ['program-steps', programId] })
  } else {
    void qc.invalidateQueries({ queryKey: ['program-steps'] })
  }
}

export function useProgramMutations() {
  const qc = useQueryClient()
  const { user } = useAuth()

  const create = useMutation({
    mutationFn: (
      payload: Omit<ProgramCreate, 'company_id'> & { company_id?: string },
    ) =>
      programsApi.createProgram({
        ...payload,
        company_id: payload.company_id ?? user!.company_id,
      }),
    onSuccess: (program) => {
      qc.setQueryData(['program', program.id], program)
      invalidateProgramCaches(qc)
    },
  })

  const update = useMutation({
    mutationFn: ({ id, payload }: { id: string; payload: ProgramUpdate }) =>
      programsApi.updateProgram(id, payload),
    onSuccess: (program) => {
      qc.setQueryData(['program', program.id], program)
      invalidateProgramCaches(qc, program.id)
    },
  })

  const publish = useMutation({
    mutationFn: (id: string) => programsApi.publishProgram(id),
    onSuccess: (program) => {
      qc.setQueryData(['program', program.id], program)
      invalidateProgramCaches(qc, program.id)
    },
  })

  const archive = useMutation({
    mutationFn: (id: string) => programsApi.archiveProgram(id),
    onMutate: async (id) => {
      await qc.cancelQueries({ queryKey: ['programs'] })
      await qc.cancelQueries({ queryKey: ['program', id] })
      const previousLists = qc.getQueriesData<Program[]>({ queryKey: ['programs'] })
      const previousProgram = qc.getQueryData<Program>(['program', id])
      qc.setQueriesData<Program[]>({ queryKey: ['programs'] }, (old) =>
        old
          ? old.map((p) => (p.id === id ? { ...p, is_active: false } : p))
          : old,
      )
      if (previousProgram) {
        qc.setQueryData(['program', id], {
          ...previousProgram,
          is_active: false,
        })
      }
      return { previousLists, previousProgram }
    },
    onError: (_err, id, context) => {
      if (!context) return
      for (const [key, data] of context.previousLists) {
        qc.setQueryData(key, data)
      }
      if (context.previousProgram) {
        qc.setQueryData(['program', id], context.previousProgram)
      }
    },
    onSettled: (_data, _err, id) => invalidateProgramCaches(qc, id),
  })

  return { create, update, publish, archive }
}

export function useStepMutations(programId: string | undefined) {
  const qc = useQueryClient()

  const invalidate = () => {
    if (programId) {
      void qc.invalidateQueries({ queryKey: ['program-steps', programId] })
    }
    void qc.invalidateQueries({ queryKey: ['programs'] })
  }

  const create = useMutation({
    mutationFn: (payload: StepCreate) => {
      if (!programId) throw new Error('Program ID is required')
      return programsApi.createProgramStep(programId, payload)
    },
    onSuccess: invalidate,
  })

  const update = useMutation({
    mutationFn: ({ id, payload }: { id: string; payload: StepUpdate }) =>
      programsApi.updateStep(id, payload),
    onSuccess: invalidate,
  })

  const remove = useMutation({
    mutationFn: (stepId: string) => programsApi.deleteStep(stepId),
    onMutate: async (stepId) => {
      if (!programId) return { previous: undefined }
      await qc.cancelQueries({ queryKey: ['program-steps', programId] })
      const previous = qc.getQueryData<Step[]>(['program-steps', programId])
      qc.setQueryData<Step[]>(['program-steps', programId], (old) =>
        old ? old.filter((s) => s.id !== stepId) : old,
      )
      return { previous }
    },
    onError: (_err, _id, context) => {
      if (programId && context?.previous) {
        qc.setQueryData(['program-steps', programId], context.previous)
      }
    },
    onSettled: invalidate,
  })

  const reorder = useMutation({
    mutationFn: (stepIds: string[]) => {
      if (!programId) throw new Error('Program ID is required')
      return programsApi.reorderProgramSteps(programId, { step_ids: stepIds })
    },
    onMutate: async (stepIds) => {
      if (!programId) return { previous: undefined }
      await qc.cancelQueries({ queryKey: ['program-steps', programId] })
      const previous = qc.getQueryData<Step[]>(['program-steps', programId])
      if (previous) {
        const byId = new Map(previous.map((s) => [s.id, s]))
        const next = stepIds
          .map((id, index) => {
            const step = byId.get(id)
            return step ? { ...step, position: index } : null
          })
          .filter((s): s is Step => s !== null)
        qc.setQueryData(['program-steps', programId], next)
      }
      return { previous }
    },
    onError: (_err, _ids, context) => {
      if (programId && context?.previous) {
        qc.setQueryData(['program-steps', programId], context.previous)
      }
    },
    onSuccess: (steps) => {
      if (programId) {
        qc.setQueryData(['program-steps', programId], steps)
      }
    },
    onSettled: invalidate,
  })

  return { create, update, remove, reorder }
}

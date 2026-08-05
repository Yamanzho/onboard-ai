import type {
  Program,
  ProgramCreate,
  ProgramListParams,
  ProgramUpdate,
} from '../types/program'
import type {
  Step,
  StepCreate,
  StepReorderRequest,
  StepUpdate,
} from '../types/step'
import { apiRequest } from './apiClient'

export async function listPrograms(
  params: ProgramListParams,
): Promise<Program[]> {
  const search = new URLSearchParams()
  search.set('company_id', params.company_id)
  if (params.is_active !== undefined) {
    search.set('is_active', String(params.is_active))
  }
  if (params.offset !== undefined) search.set('offset', String(params.offset))
  if (params.limit !== undefined) search.set('limit', String(params.limit))
  return apiRequest<Program[]>(`/api/v1/programs?${search}`)
}

export async function getProgram(programId: string): Promise<Program> {
  return apiRequest<Program>(`/api/v1/programs/${programId}`)
}

export async function createProgram(payload: ProgramCreate): Promise<Program> {
  return apiRequest<Program>('/api/v1/programs', {
    method: 'POST',
    body: payload,
  })
}

export async function updateProgram(
  programId: string,
  payload: ProgramUpdate,
): Promise<Program> {
  return apiRequest<Program>(`/api/v1/programs/${programId}`, {
    method: 'PATCH',
    body: payload,
  })
}

export async function publishProgram(programId: string): Promise<Program> {
  return apiRequest<Program>(`/api/v1/programs/${programId}/publish`, {
    method: 'POST',
  })
}

export async function archiveProgram(programId: string): Promise<Program> {
  return apiRequest<Program>(`/api/v1/programs/${programId}/archive`, {
    method: 'POST',
  })
}

export async function listProgramSteps(programId: string): Promise<Step[]> {
  return apiRequest<Step[]>(`/api/v1/programs/${programId}/steps`)
}

export async function createProgramStep(
  programId: string,
  payload: StepCreate,
): Promise<Step> {
  return apiRequest<Step>(`/api/v1/programs/${programId}/steps`, {
    method: 'POST',
    body: payload,
  })
}

export async function reorderProgramSteps(
  programId: string,
  payload: StepReorderRequest,
): Promise<Step[]> {
  return apiRequest<Step[]>(`/api/v1/programs/${programId}/steps/reorder`, {
    method: 'POST',
    body: payload,
  })
}

export async function updateStep(
  stepId: string,
  payload: StepUpdate,
): Promise<Step> {
  return apiRequest<Step>(`/api/v1/steps/${stepId}`, {
    method: 'PATCH',
    body: payload,
  })
}

export async function deleteStep(stepId: string): Promise<void> {
  return apiRequest<void>(`/api/v1/steps/${stepId}`, {
    method: 'DELETE',
  })
}

import type { StepType } from '../../types/step'

export interface StepFormValues {
  title: string
  description: string
  step_type: StepType
  content_body: string
  is_required: boolean
  estimated_minutes: string
}

export function stepContentBody(content: Record<string, unknown> | undefined) {
  if (!content) return ''
  const body = content.body
  return typeof body === 'string' ? body : ''
}

export function buildStepContent(
  body: string,
  existing?: Record<string, unknown>,
): Record<string, unknown> {
  const next = { ...(existing ?? {}) }
  const trimmed = body.trim()
  if (trimmed) next.body = trimmed
  else delete next.body
  return next
}

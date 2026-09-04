export type StepType = 'content' | 'task' | 'quiz' | 'ack'

export interface ContentBlock {
  id: string
  type: string
  text: string
}

export interface Step {
  id: string
  program_id: string
  title: string
  description: string | null
  step_type: StepType | string
  position: number
  content: Record<string, unknown>
  content_blocks?: ContentBlock[]
  block_count?: number
  is_required: boolean
  estimated_minutes: number | null
  created_at: string
  updated_at: string
}

export interface StepCreate {
  title: string
  description?: string | null
  step_type?: StepType
  position?: number | null
  content?: Record<string, unknown>
  is_required?: boolean
  estimated_minutes?: number | null
}

export interface StepUpdate {
  title?: string
  description?: string | null
  step_type?: StepType
  content?: Record<string, unknown>
  is_required?: boolean
  estimated_minutes?: number | null
}

export interface StepReorderRequest {
  step_ids: string[]
}

export const STEP_TYPES: StepType[] = ['content', 'task', 'quiz', 'ack']

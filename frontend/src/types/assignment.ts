export type AssignmentStatus =
  | 'pending'
  | 'in_progress'
  | 'completed'
  | 'cancelled'

export interface Assignment {
  id: string
  company_id: string
  employee_id: string
  program_id: string
  assigned_by_id: string | null
  status: AssignmentStatus | string
  assigned_at: string
  due_at: string | null
  started_at: string | null
  completed_at: string | null
  created_at: string
  updated_at: string
}

export interface AssignmentCreate {
  employee_id: string
  program_id: string
  assigned_by_id?: string | null
  due_at?: string | null
}

export interface AssignmentListParams {
  company_id: string
  status?: AssignmentStatus | string
  employee_id?: string
  offset?: number
  limit?: number
}

export interface ProgressItem {
  id: string
  assignment_id: string
  step_id: string
  status: string
  payload: Record<string, unknown>
  started_at: string | null
  completed_at: string | null
  created_at: string
  updated_at: string
}

export interface AssignmentProgress {
  percentage: number
  items: ProgressItem[]
}

export const ASSIGNMENT_STATUSES: AssignmentStatus[] = [
  'pending',
  'in_progress',
  'completed',
  'cancelled',
]

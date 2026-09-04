export type AssignmentStatus =
  | 'pending'
  | 'in_progress'
  | 'completed'
  | 'cancelled'

export type AssignmentPriority = 'normal' | 'important' | 'critical'

export interface Assignment {
  id: string
  company_id: string
  employee_id: string
  program_id: string
  assigned_by_id: string | null
  status: AssignmentStatus | string
  priority?: AssignmentPriority | string
  source_batch_id?: string | null
  overdue?: boolean
  /** Course revision captured when this assignment was created. */
  program_revision?: number
  has_structure_snapshot?: boolean
  assigned_at: string
  due_at: string | null
  started_at: string | null
  completed_at: string | null
  created_at: string
  updated_at: string
}

export interface AssignmentCreate {
  employee_id?: string
  employee_ids?: string[]
  department_ids?: string[]
  program_id: string
  assigned_by_id?: string | null
  due_at?: string | null
  priority?: AssignmentPriority | string
  deadline_overrides?: Record<string, string>
}

export interface AssignmentBulkCreateResult {
  items: Assignment[]
  source_batch_id: string | null
  count: number
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
  block_index?: number | null
  started_at: string | null
  completed_at: string | null
  created_at: string
  updated_at: string
  step?: {
    title: string
    description?: string | null
    step_type?: string
    content?: Record<string, unknown>
    content_blocks?: { id: string; type: string; text: string }[]
    block_count?: number
    position?: number
  } | null
}

export interface AssignmentProgress {
  percentage: number
  items: ProgressItem[]
  program_id?: string | null
  assignment_status?: string | null
}

export const ASSIGNMENT_STATUSES: AssignmentStatus[] = [
  'pending',
  'in_progress',
  'completed',
  'cancelled',
]

export const ASSIGNMENT_PRIORITIES: AssignmentPriority[] = [
  'critical',
  'important',
  'normal',
]

export type ReminderMode = 'default' | 'reduced' | 'disabled'
export type AssignmentOutboundKind =
  | 'assignment_initial'
  | 'assignment_reminder'
  | 'assignment_manual_reminder'

export interface ReminderPreference {
  mode: ReminderMode
  acknowledged_until_date: string | null
  last_acknowledged_at: string | null
  last_automated_reminder_at: string | null
  last_manual_reminder_at: string | null
  updated_by_employee_at: string | null
  updated_at: string | null
}

export interface AssignmentNotificationItem {
  id: string
  source_type: AssignmentOutboundKind | string
  created_at: string
  sent_at: string | null
  status: string
  preview: string
  last_error_category: string | null
}

export interface AssignmentNotifications {
  assignment_id: string
  program_title: string
  preference: ReminderPreference
  items: AssignmentNotificationItem[]
}

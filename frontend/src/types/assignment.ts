export type AssignmentStatus =
  | 'pending'
  | 'in_progress'
  | 'completed'
  | 'cancelled'

export type AssignmentPriority = 'normal' | 'important' | 'critical'
export type AssignmentType = 'program' | 'acknowledgement'

export interface AcknowledgementSummary {
  total_documents: number
  required_documents: number
  acknowledged_required_count: number
  completed: boolean
  title?: string | null
  percentage?: number
}

export interface AcknowledgementDocumentInput {
  article_id: string
  position: number
  is_required: boolean
}

export interface Assignment {
  id: string
  company_id: string
  employee_id: string
  assignment_type?: AssignmentType | string
  program_id: string | null
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
  acknowledgement?: AcknowledgementSummary | null
}

export interface AssignmentCreate {
  assignment_type?: AssignmentType | string
  employee_id?: string
  employee_ids?: string[]
  department_ids?: string[]
  program_id?: string | null
  documents?: AcknowledgementDocumentInput[]
  assigned_by_id?: string | null
  due_at?: string | null
  priority?: AssignmentPriority | string
  deadline_overrides?: Record<string, string>
}

export interface AcknowledgementItem {
  id: string
  assignment_id: string
  article_id: string
  article_version_id: string
  position: number
  is_required: boolean
  acknowledged_at: string | null
  title: string
  version: number
  body_format: string
}

export interface AcknowledgementItemList {
  items: AcknowledgementItem[]
  assignment_id: string
  assignment_status: string
  acknowledgement: AcknowledgementSummary
}

export interface AcknowledgementDocumentView {
  item: AcknowledgementItem
  body: string
  assignment_status: string
}

export interface AcknowledgementAction {
  item: AcknowledgementItem
  assignment_status: string
  acknowledgement: AcknowledgementSummary
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

export const ASSIGNMENT_TYPES: AssignmentType[] = ['program', 'acknowledgement']

export function isAcknowledgementAssignment(assignment: Assignment): boolean {
  return assignment.assignment_type === 'acknowledgement'
}

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

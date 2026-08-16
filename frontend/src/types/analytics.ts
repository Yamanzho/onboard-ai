export interface CompletionByProgram {
  program_id: string
  title: string
  assigned: number
  completed: number
  completion_rate: number | null
}

export interface CompletionOverTimePoint {
  date: string
  count: number
}

export interface OnboardingAnalytics {
  total_employees: number
  active_onboarding: number
  completed_onboarding: number
  cancelled_onboarding: number
  completion_rate: number | null
  average_progress: number | null
  employees_not_started: number
  employees_in_progress: number
  employees_completed: number
  by_program: CompletionByProgram[]
  completed_over_time: CompletionOverTimePoint[]
}

export interface CompanyAuditLog {
  id: string
  company_id: string
  actor_employee_id: string | null
  actor_name: string | null
  action: string
  resource_type: string
  resource_id: string | null
  summary: string
  details: Record<string, unknown>
  created_at: string
}

export interface CompanyAuditLogListResponse {
  items: CompanyAuditLog[]
}

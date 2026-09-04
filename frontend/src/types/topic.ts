import type { DepartmentSummary } from './department'

export interface ManagerSummary {
  id: string
  full_name: string
  job_title: string | null
  status: string
}

export interface TopicResponsibility {
  id: string
  topic_id: string
  department_id: string | null
  employee_id: string | null
  department: DepartmentSummary | null
  employee: ManagerSummary | null
  created_at: string
  updated_at: string
}

export interface QuestionTopic {
  id: string
  company_id: string
  name: string
  slug: string
  description: string | null
  is_active: boolean
  responsibility: TopicResponsibility | null
  created_at: string
  updated_at: string
}

export interface QuestionTopicCreate {
  company_id: string
  name: string
  slug?: string | null
  description?: string | null
  is_active?: boolean
  department_id?: string | null
  employee_id?: string | null
}

export interface QuestionTopicUpdate {
  name?: string
  slug?: string | null
  description?: string | null
  is_active?: boolean
}

export interface TopicResponsibilityPayload {
  department_id?: string | null
  employee_id?: string | null
}

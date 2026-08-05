export type EmployeeRole = 'admin' | 'hr' | 'employee'
export type EmployeeStatus = 'invited' | 'active' | 'archived'

export interface Employee {
  id: string
  company_id: string
  telegram_user_id: number
  telegram_chat_id: number | null
  telegram_username: string | null
  full_name: string
  email: string | null
  role: EmployeeRole | string
  status: EmployeeStatus | string
  hired_at: string | null
  created_at: string
  updated_at: string
}

export interface EmployeeCreate {
  company_id: string
  telegram_user_id: number
  full_name: string
  email?: string | null
  telegram_chat_id?: number | null
  telegram_username?: string | null
  role?: EmployeeRole
  status?: EmployeeStatus
  hired_at?: string | null
}

export interface EmployeeUpdate {
  telegram_user_id?: number
  telegram_chat_id?: number | null
  telegram_username?: string | null
  full_name?: string
  email?: string | null
  role?: EmployeeRole
  status?: EmployeeStatus
  hired_at?: string | null
}

export interface EmployeeListParams {
  company_id: string
  status?: EmployeeStatus | string
  offset?: number
  limit?: number
}

export const EMPLOYEE_ROLES: EmployeeRole[] = ['employee', 'hr', 'admin']
export const EMPLOYEE_STATUSES: EmployeeStatus[] = ['invited', 'active', 'archived']

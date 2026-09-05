export type EmployeeRole = 'admin' | 'hr' | 'employee'

/** Cookie-only browser auth acknowledgement (no raw tokens). */
export interface BrowserSessionResponse {
  token_type: string
}

/** @deprecated Prefer BrowserSessionResponse for browser flows. */
export interface TokenResponse {
  access_token?: string
  refresh_token?: string
  token_type: string
}

export interface CurrentUser {
  id: string
  company_id: string
  full_name: string
  email: string | null
  role: EmployeeRole | string
  status: string
  telegram_user_id: number
  telegram_username: string | null
  telegram_connected?: boolean
  company_name?: string | null
  company_description?: string | null
  hired_at?: string | null
  department_id?: string | null
  manager_id?: string | null
  job_title?: string | null
  capabilities?: string[]
  created_at: string
  updated_at: string
}

export interface ProfileUpdatePayload {
  full_name?: string
  email?: string | null
}

export interface PasswordChangePayload {
  current_password: string
  new_password: string
  confirm_password: string
}

export interface PasswordResetPreview {
  full_name: string
  email: string
  company_name: string | null
  expires_at: string
  purpose: 'password_reset'
}

export interface PasswordResetConfirmPayload {
  token: string
  new_password: string
  confirm_password: string
}

export interface PasswordResetInitiateResult {
  email_sent: boolean
  delivery: 'email' | 'manual_url'
  reset_url: string | null
  detail: string
}

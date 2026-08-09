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
  created_at: string
  updated_at: string
}

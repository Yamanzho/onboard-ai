export interface SuperAdminUser {
  id: string
  email: string
  full_name: string
  role: 'super_admin' | string
  is_active: boolean
  created_at: string
  updated_at: string
}

export interface PlatformDashboardStats {
  companies_count: number
  active_companies: number
  trial_companies: number
  expired_companies: number
  employees_count: number
  active_assignments_count: number
}

export interface PlatformCompany {
  id: string
  name: string
  slug: string
  timezone: string
  is_active: boolean
  settings: Record<string, unknown>
  description?: string | null
  logo_url?: string | null
  contact_email?: string | null
  contact_phone?: string | null
  contact_person?: string | null
  created_at: string
  updated_at: string
}

export type SubscriptionTier = 'starter' | 'professional' | 'enterprise'
export type SubscriptionStatus =
  | 'trial'
  | 'active'
  | 'suspended'
  | 'expired'
  | 'blocked'
export type PaymentStatus = 'unpaid' | 'paid' | 'past_due'

export interface CompanySubscription {
  id: string
  company_id: string
  tier: SubscriptionTier | string
  status: SubscriptionStatus | string
  payment_status: PaymentStatus | string
  started_at: string
  ends_at: string | null
  auto_renew: boolean
  employee_limit: number
  program_limit: number
  is_current: boolean
  created_at: string
  updated_at: string
}

export interface CompanySubscriptionUpdate {
  tier?: SubscriptionTier
  status?: SubscriptionStatus
  payment_status?: PaymentStatus
  started_at?: string
  ends_at?: string | null
  auto_renew?: boolean
}

export interface SubscriptionHistoryEvent {
  id: string
  company_id: string
  subscription_id: string | null
  event_type: string
  previous_status: string | null
  new_status: string | null
  previous_tier: string | null
  new_tier: string | null
  note: string | null
  created_at: string
}

export interface CompanyLimits {
  company_id: string
  employee_limit: number
  employees_used: number
  program_limit: number
  programs_used: number
}

export interface PlatformCompanyDetail extends PlatformCompany {
  employees_count: number
  programs_count: number
  assignments_count: number
  subscription: CompanySubscription | null
  limits: CompanyLimits | null
}

export interface PlatformCompanyCreate {
  name: string
  slug: string
  timezone?: string
  settings?: Record<string, unknown>
  description?: string | null
  logo_url?: string | null
  contact_email?: string | null
  contact_phone?: string | null
  contact_person?: string | null
  admin_full_name: string
  admin_email: string
  admin_telegram_user_id: number
}

export interface PlatformCompanyUpdate {
  name?: string
  slug?: string
  timezone?: string
  is_active?: boolean
  settings?: Record<string, unknown>
}

export interface PlatformCompanyProfileUpdate {
  name?: string
  slug?: string
  timezone?: string
  description?: string | null
  logo_url?: string | null
  contact_email?: string | null
  contact_phone?: string | null
  contact_person?: string | null
  is_active?: boolean
}

export interface PlatformUser {
  id: string
  company_id: string
  company_name: string | null
  company_slug: string | null
  full_name: string
  email: string | null
  role: string
  status: string
  telegram_user_id: number
  telegram_username: string | null
  last_login_at: string | null
  created_at: string
  updated_at: string
  invite_email_sent?: boolean | null
  invite_delivery?: 'email' | 'manual_url' | null
  invite_url?: string | null
  invite_detail?: string | null
  invite_telegram_url?: string | null
}

export interface PlatformUserUpdate {
  role?: 'admin' | 'hr' | 'employee'
  status?: 'invited' | 'active' | 'archived'
}

export interface CompanyUserCreate {
  full_name: string
  email: string
  role?: 'admin' | 'hr' | 'employee'
  telegram_user_id?: number | null
}

export interface InvitePreview {
  employee_id: string
  full_name: string
  email: string
  company_name: string | null
  expires_at: string
  purpose: 'employee' | 'hr' | 'admin'
  role: 'employee' | 'hr' | 'admin'
}

export interface InviteAcceptPayload {
  token: string
  password: string
}

export interface PlatformAuditLog {
  id: string
  super_admin_id: string | null
  action: string
  resource_type: string
  resource_id: string | null
  company_id: string | null
  summary: string
  details: Record<string, unknown>
  created_at: string
}

export interface PlatformSettings {
  maintenance_mode: boolean
  allow_new_companies: boolean
  default_timezone: string
  notes: string
}

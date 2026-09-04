export interface Department {
  id: string
  company_id: string
  name: string
  slug: string
  description: string | null
  is_active: boolean
  created_at: string
  updated_at: string
}

export interface DepartmentSummary {
  id: string
  name: string
  slug: string
  is_active: boolean
}

export interface DepartmentCreate {
  company_id: string
  name: string
  slug?: string | null
  description?: string | null
  is_active?: boolean
}

export interface DepartmentUpdate {
  name?: string
  slug?: string | null
  description?: string | null
  is_active?: boolean
}

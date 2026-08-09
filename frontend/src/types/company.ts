export interface Company {
  id: string
  name: string
  slug: string
  timezone: string
  is_active: boolean
  settings: Record<string, unknown>
  created_at: string
  updated_at: string
}

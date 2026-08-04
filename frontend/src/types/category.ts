export interface Category {
  id: string
  company_id: string
  parent_id: string | null
  name: string
  slug: string
  position: number
  created_at: string
  updated_at: string
}

export interface CategoryCreate {
  company_id: string
  name: string
  slug?: string | null
  parent_id?: string | null
  position?: number
}

export interface CategoryUpdate {
  name?: string
  slug?: string | null
  parent_id?: string | null
  position?: number
}

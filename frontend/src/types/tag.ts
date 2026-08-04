export interface Tag {
  id: string
  company_id: string
  name: string
  slug: string
  created_at: string
  updated_at: string
}

export interface TagCreate {
  company_id: string
  name: string
  slug?: string | null
}

export interface TagUpdate {
  name?: string
  slug?: string | null
}

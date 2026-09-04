export type ProgramStatusFilter = 'all' | 'published' | 'draft'

export interface Program {
  id: string
  company_id: string
  title: string
  description: string | null
  /** True when published; False for draft / archived (API has no separate archived). */
  is_active: boolean
  /** Course structure/content generation. Starts at 1. */
  revision?: number
  /** True when pending or in_progress assignments exist. */
  structure_locked?: boolean
  /** False when structure_locked is true. */
  can_edit_structure?: boolean
  created_at: string
  updated_at: string
}

export interface ProgramCreate {
  company_id: string
  title: string
  description?: string | null
}

export interface ProgramUpdate {
  title?: string
  description?: string | null
}

export interface ProgramListParams {
  company_id: string
  is_active?: boolean
  offset?: number
  limit?: number
}

export function programStatusLabel(program: Program): 'Published' | 'Draft' {
  return program.is_active ? 'Published' : 'Draft'
}

export function programRevision(program: Program): number {
  return program.revision ?? 1
}

export function programStructureLocked(program: Program): boolean {
  return program.structure_locked === true
}

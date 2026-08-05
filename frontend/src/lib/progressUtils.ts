import type { Assignment, AssignmentProgress, ProgressItem } from '../types/assignment'
import type { Step } from '../types/step'
import { t } from '../i18n'

const DONE = new Set(['completed', 'skipped'])

export function isAssignmentOverdue(assignment: Assignment, now = new Date()): boolean {
  if (!assignment.due_at) return false
  if (assignment.status === 'completed' || assignment.status === 'cancelled') {
    return false
  }
  return new Date(assignment.due_at).getTime() < now.getTime()
}

export function isActiveAssignment(assignment: Assignment): boolean {
  return assignment.status === 'pending' || assignment.status === 'in_progress'
}

export function currentStepTitle(
  progress: AssignmentProgress | undefined,
  steps: Step[],
): string {
  if (!progress || progress.items.length === 0) return t('common.emDash')
  const byId = new Map(steps.map((s) => [s.id, s]))
  const ordered = [...progress.items].sort((a, b) => {
    const pa = byId.get(a.step_id)?.position ?? 0
    const pb = byId.get(b.step_id)?.position ?? 0
    return pa - pb
  })
  const current = ordered.find((item) => !DONE.has(item.status))
  if (!current) return t('dashboard.stepCompleted')
  return byId.get(current.step_id)?.title ?? t('dashboard.stepFallback')
}

export function lastActivityAt(
  assignment: Assignment,
  progress: AssignmentProgress | undefined,
): string | null {
  const dates: number[] = []
  if (assignment.updated_at) dates.push(new Date(assignment.updated_at).getTime())
  if (assignment.started_at) dates.push(new Date(assignment.started_at).getTime())
  if (assignment.completed_at) dates.push(new Date(assignment.completed_at).getTime())
  for (const item of progress?.items ?? []) {
    if (item.completed_at) dates.push(new Date(item.completed_at).getTime())
    if (item.updated_at) dates.push(new Date(item.updated_at).getTime())
  }
  if (dates.length === 0) return null
  return new Date(Math.max(...dates)).toISOString()
}

export function averageProgress(
  progressList: Array<AssignmentProgress | undefined>,
): number {
  const values = progressList
    .map((p) => p?.percentage)
    .filter((n): n is number => typeof n === 'number')
  if (values.length === 0) return 0
  const sum = values.reduce((acc, n) => acc + n, 0)
  return Math.round((sum / values.length) * 100) / 100
}

export function hasPayload(item: ProgressItem): boolean {
  return Object.keys(item.payload ?? {}).length > 0
}

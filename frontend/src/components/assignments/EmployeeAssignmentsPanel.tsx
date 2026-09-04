import { Link } from 'react-router-dom'
import {
  EmptyState,
  ErrorAlert,
  LoadingBlock,
} from '../common/PageHeader'
import { AssignmentStatusBadge } from './AssignmentStatusBadge'
import { AssignmentPriorityBadge } from './AssignmentPriorityBadge'
import { Button } from '../ui/Button'
import { useEmployeeAssignments } from '../../hooks/useAssignments'
import { usePrograms } from '../../hooks/usePrograms'
import { useWorkspacePaths } from '../../hooks/useWorkspacePaths'
import { useQueries } from '@tanstack/react-query'
import { t } from '../../i18n'
import { assignmentTitle, isAssignmentOverdue } from '../../lib/progressUtils'
import * as assignmentsApi from '../../services/assignmentsApi'

function formatDate(value: string | null | undefined) {
  if (!value) return t('common.emDash')
  try {
    return new Date(value).toLocaleDateString()
  } catch {
    return value
  }
}

export function EmployeeAssignmentsPanel({
  employeeId,
}: {
  employeeId: string
}) {
  const paths = useWorkspacePaths()
  const { data, isLoading, error } = useEmployeeAssignments(employeeId)
  const { data: programs = [] } = usePrograms()
  const assignments = data ?? []

  const programTitle = (id: string) =>
    programs.find((p) => p.id === id)?.title ?? id.slice(0, 8)

  const progressQueries = useQueries({
    queries: assignments.map((a) => ({
      queryKey: ['assignment-progress', a.id],
      queryFn: () => assignmentsApi.getAssignmentProgress(a.id),
      enabled: a.assignment_type !== 'acknowledgement',
    })),
  })

  if (isLoading) {
    return <LoadingBlock label={t('assignments.panel.loading')} />
  }
  if (error) return <ErrorAlert message={(error as Error).message} />

  if (assignments.length === 0) {
    return (
      <EmptyState
        title={t('assignments.panel.emptyTitle')}
        description={t('assignments.panel.emptyDescription')}
        actionLabel={t('assignments.create')}
        actionTo={paths.assignmentNew}
      />
    )
  }

  return (
    <div className="overflow-hidden rounded-lg border border-[var(--color-border)] bg-white">
      <table className="min-w-full text-left text-sm">
        <thead className="bg-slate-50 text-xs uppercase text-[var(--color-muted)]">
          <tr>
            <th className="px-4 py-3">{t('assignments.colProgram')}</th>
            <th className="px-4 py-3">{t('common.status')}</th>
            <th className="px-4 py-3">{t('assignments.colPriority')}</th>
            <th className="px-4 py-3">{t('assignments.progress')}</th>
            <th className="px-4 py-3">{t('assignments.panel.colDue')}</th>
            <th className="px-4 py-3" />
          </tr>
        </thead>
        <tbody className="divide-y divide-[var(--color-border)]">
          {assignments.map((assignment, index) => {
            const pct =
              assignment.assignment_type === 'acknowledgement'
                ? assignment.acknowledgement?.percentage
                : progressQueries[index]?.data?.percentage
            const overdue = isAssignmentOverdue(assignment)
            return (
              <tr key={assignment.id} className={overdue ? 'bg-red-50/40' : undefined}>
                <td className="px-4 py-3 font-medium">
                  {assignmentTitle(assignment, programTitle)}
                </td>
                <td className="px-4 py-3">
                  <AssignmentStatusBadge status={assignment.status} />
                </td>
                <td className="px-4 py-3">
                  <AssignmentPriorityBadge priority={assignment.priority} />
                </td>
                <td className="px-4 py-3 text-[var(--color-muted)]">
                  {progressQueries[index]?.isLoading
                    ? '…'
                    : pct != null
                      ? `${pct}%`
                      : t('common.emDash')}
                </td>
                <td className="px-4 py-3 text-[var(--color-muted)]">
                  <span>{formatDate(assignment.due_at)}</span>
                  {overdue ? (
                    <span className="ml-2 text-xs font-medium text-[var(--color-danger)]">
                      {t('assignments.overdue')}
                    </span>
                  ) : null}
                </td>
                <td className="px-4 py-3 text-right">
                  <Link to={paths.assignment(assignment.id)}>
                    <Button variant="secondary">{t('common.view')}</Button>
                  </Link>
                </td>
              </tr>
            )
          })}
        </tbody>
      </table>
    </div>
  )
}

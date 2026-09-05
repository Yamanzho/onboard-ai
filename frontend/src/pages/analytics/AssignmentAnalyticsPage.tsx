import { useMemo } from 'react'
import { Link } from 'react-router-dom'
import {
  EmptyState,
  ErrorAlert,
  LoadingBlock,
  PageHeader,
} from '../../components/common/PageHeader'
import { AssignmentStatusBadge } from '../../components/assignments/AssignmentStatusBadge'
import { AssignmentPriorityBadge } from '../../components/assignments/AssignmentPriorityBadge'
import { useAssignmentAnalytics } from '../../hooks/useAnalytics'
import { useAssignments } from '../../hooks/useAssignments'
import { useEmployees } from '../../hooks/useEmployees'
import { usePrograms } from '../../hooks/usePrograms'
import { useWorkspacePaths } from '../../hooks/useWorkspacePaths'
import { labelAssignmentType, t } from '../../i18n'
import {
  assignmentTitle,
  compareAssignmentsByPriorityDeadline,
  isActiveAssignment,
  isAssignmentOverdue,
} from '../../lib/progressUtils'

function StatCard({
  label,
  value,
  emphasize,
}: {
  label: string
  value: string
  emphasize?: boolean
}) {
  return (
    <div className="rounded-lg border border-[var(--color-border)] bg-white px-4 py-4">
      <p className="text-xs uppercase tracking-wide text-[var(--color-muted)]">
        {label}
      </p>
      <p
        className={`mt-1 text-2xl font-semibold ${
          emphasize ? 'text-[var(--color-danger)]' : ''
        }`}
      >
        {value}
      </p>
    </div>
  )
}

export function AssignmentAnalyticsPage() {
  const paths = useWorkspacePaths()
  const {
    data: analytics,
    isLoading: analyticsLoading,
    error: analyticsError,
  } = useAssignmentAnalytics()
  const {
    data: assignments = [],
    isLoading: assignmentsLoading,
    error: assignmentsError,
  } = useAssignments()
  const { data: employees = [] } = useEmployees()
  const { data: programs = [] } = usePrograms()

  const employeeName = useMemo(() => {
    const map = new Map(employees.map((e) => [e.id, e.full_name]))
    return (id: string) => map.get(id) ?? id.slice(0, 8)
  }, [employees])
  const programTitle = useMemo(() => {
    const map = new Map(programs.map((p) => [p.id, p.title]))
    return (id: string) => map.get(id) ?? id.slice(0, 8)
  }, [programs])

  const nearest = useMemo(
    () =>
      assignments
        .filter((a) => isActiveAssignment(a) && a.due_at)
        .sort(compareAssignmentsByPriorityDeadline)
        .slice(0, 5),
    [assignments],
  )
  const overdueItems = useMemo(
    () =>
      assignments
        .filter((a) => isAssignmentOverdue(a))
        .sort(compareAssignmentsByPriorityDeadline)
        .slice(0, 5),
    [assignments],
  )

  const loading = analyticsLoading || assignmentsLoading
  const errorMessage =
    (analyticsError instanceof Error && analyticsError.message) ||
    (assignmentsError instanceof Error && assignmentsError.message) ||
    null

  return (
    <div>
      <PageHeader
        title={t('analytics.title')}
        description={t('analytics.description')}
      />
      <p className="mb-4 text-xs text-[var(--color-muted)]">{t('analytics.formula')}</p>
      {errorMessage ? <ErrorAlert message={errorMessage} /> : null}
      {loading ? (
        <LoadingBlock />
      ) : (
        <>
          <div className="mb-6 grid gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-6">
            <StatCard
              label={t('analytics.active')}
              value={String(analytics?.active ?? 0)}
            />
            <StatCard
              label={t('analytics.overdue')}
              value={String(analytics?.overdue ?? 0)}
              emphasize={(analytics?.overdue ?? 0) > 0}
            />
            <StatCard
              label={t('analytics.completed')}
              value={String(analytics?.completed ?? 0)}
            />
            <StatCard
              label={t('analytics.completionRate')}
              value={
                analytics?.completion_rate == null
                  ? t('common.emDash')
                  : `${analytics.completion_rate}%`
              }
            />
            <StatCard
              label={t('analytics.employeesActive')}
              value={String(analytics?.employees_with_active ?? 0)}
            />
            <StatCard
              label={t('analytics.employeesOverdue')}
              value={String(analytics?.employees_with_overdue ?? 0)}
              emphasize={(analytics?.employees_with_overdue ?? 0) > 0}
            />
          </div>

          {analytics?.by_type && Object.keys(analytics.by_type).length > 0 ? (
            <section className="mb-6 overflow-x-auto rounded-lg border border-[var(--color-border)] bg-white">
              <h2 className="px-4 pt-4 text-sm font-semibold">
                {t('analytics.byType')}
              </h2>
              <table className="mt-2 min-w-full text-left text-sm">
                <thead className="bg-slate-50 text-xs uppercase text-[var(--color-muted)]">
                  <tr>
                    <th className="px-4 py-2">{t('assignments.assignmentType')}</th>
                    <th className="px-4 py-2">{t('analytics.active')}</th>
                    <th className="px-4 py-2">{t('analytics.overdue')}</th>
                    <th className="px-4 py-2">{t('analytics.completed')}</th>
                    <th className="px-4 py-2">{t('analytics.completionRate')}</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-[var(--color-border)]">
                  {Object.entries(analytics.by_type).map(([type, row]) => (
                    <tr key={type}>
                      <td className="px-4 py-2">{labelAssignmentType(type)}</td>
                      <td className="px-4 py-2">{row.active}</td>
                      <td className="px-4 py-2">{row.overdue}</td>
                      <td className="px-4 py-2">{row.completed}</td>
                      <td className="px-4 py-2">
                        {row.completion_rate == null
                          ? t('common.emDash')
                          : `${row.completion_rate}%`}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </section>
          ) : null}

          <div className="grid gap-6 lg:grid-cols-2">
            <section className="rounded-lg border border-[var(--color-border)] bg-white p-4">
              <h2 className="mb-3 text-sm font-semibold">
                {t('analytics.nearestDeadlines')}
              </h2>
              {nearest.length === 0 ? (
                <EmptyState title={t('analytics.emptyDeadlines')} />
              ) : (
                <ul className="space-y-2 text-sm">
                  {nearest.map((a) => (
                    <li key={a.id} className="flex items-center justify-between gap-2">
                      <Link
                        to={paths.assignment(a.id)}
                        className="truncate hover:text-[var(--color-accent)]"
                      >
                        {employeeName(a.employee_id)} ·{' '}
                        {assignmentTitle(a, programTitle)}
                      </Link>
                      <AssignmentPriorityBadge priority={a.priority} />
                    </li>
                  ))}
                </ul>
              )}
            </section>
            <section className="rounded-lg border border-[var(--color-border)] bg-white p-4">
              <h2 className="mb-3 text-sm font-semibold">
                {t('analytics.overdueList')}
              </h2>
              {overdueItems.length === 0 ? (
                <EmptyState title={t('analytics.emptyOverdue')} />
              ) : (
                <ul className="space-y-2 text-sm">
                  {overdueItems.map((a) => (
                    <li key={a.id} className="flex items-center justify-between gap-2">
                      <Link
                        to={paths.assignment(a.id)}
                        className="truncate hover:text-[var(--color-accent)]"
                      >
                        {employeeName(a.employee_id)} ·{' '}
                        {assignmentTitle(a, programTitle)}
                      </Link>
                      <AssignmentStatusBadge status={a.status} />
                    </li>
                  ))}
                </ul>
              )}
            </section>
          </div>
        </>
      )}
    </div>
  )
}

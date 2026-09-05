import { useMemo } from 'react'
import { Link } from 'react-router-dom'
import {
  EmptyState,
  ErrorAlert,
  LoadingBlock,
  PageHeader,
} from '../../components/common/PageHeader'
import { AssignmentStatusBadge } from '../../components/assignments/AssignmentStatusBadge'
import { EmployeeStatusBadge } from '../../components/employees/EmployeeBadges'
import { useAssignmentAnalytics, useOnboardingAnalytics } from '../../hooks/useAnalytics'
import { useAssignments } from '../../hooks/useAssignments'
import { useAuth } from '../../hooks/useAuth'
import { useEmployees } from '../../hooks/useEmployees'
import { usePrograms } from '../../hooks/usePrograms'
import { useWorkspacePaths } from '../../hooks/useWorkspacePaths'
import { t } from '../../i18n'
import { assignmentTitle, isActiveAssignment } from '../../lib/progressUtils'

function StatCard({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border border-[var(--color-border)] bg-white px-4 py-4">
      <p className="text-xs uppercase tracking-wide text-[var(--color-muted)]">
        {label}
      </p>
      <p className="mt-1 text-2xl font-semibold">{value}</p>
    </div>
  )
}

export function HrDashboardPage() {
  const { user } = useAuth()
  const paths = useWorkspacePaths()
  const {
    data: analytics,
    isLoading: analyticsLoading,
    error: analyticsError,
  } = useOnboardingAnalytics()
  const { data: assignmentAnalytics } = useAssignmentAnalytics()
  const {
    data: employees = [],
    isLoading: employeesLoading,
    error: employeesError,
  } = useEmployees()
  const {
    data: programs = [],
    isLoading: programsLoading,
    error: programsError,
  } = usePrograms()
  const {
    data: assignments = [],
    isLoading: assignmentsLoading,
    error: assignmentsError,
  } = useAssignments()

  const staff = useMemo(
    () => employees.filter((e) => e.role === 'employee'),
    [employees],
  )

  const stats = useMemo(() => {
    const active = assignments.filter(isActiveAssignment)
    return {
      employees: staff.length,
      activeOnboarding: active.length,
    }
  }, [staff, assignments])

  const recentEmployees = useMemo(
    () =>
      [...staff]
        .sort((a, b) => b.created_at.localeCompare(a.created_at))
        .slice(0, 5),
    [staff],
  )

  const pendingOnboarding = useMemo(
    () =>
      assignments
        .filter((a) => a.status === 'pending')
        .sort((a, b) => b.created_at.localeCompare(a.created_at))
        .slice(0, 5),
    [assignments],
  )

  const recentProgress = useMemo(
    () =>
      [...assignments]
        .filter(isActiveAssignment)
        .sort((a, b) => b.updated_at.localeCompare(a.updated_at))
        .slice(0, 5),
    [assignments],
  )

  const employeeName = useMemo(() => {
    const map = new Map(employees.map((e) => [e.id, e.full_name]))
    return (id: string) => map.get(id) ?? id.slice(0, 8)
  }, [employees])

  const programTitle = useMemo(() => {
    const map = new Map(programs.map((p) => [p.id, p.title]))
    return (id: string) => map.get(id) ?? id.slice(0, 8)
  }, [programs])
  const titleOf = (assignment: (typeof assignments)[number]) =>
    assignmentTitle(assignment, programTitle)

  const loading =
    employeesLoading || programsLoading || assignmentsLoading || analyticsLoading
  const errorMessage =
    (employeesError instanceof Error && employeesError.message) ||
    (programsError instanceof Error && programsError.message) ||
    (assignmentsError instanceof Error && assignmentsError.message) ||
    (analyticsError instanceof Error && analyticsError.message) ||
    null

  return (
    <div>
      <PageHeader
        title={t('hrDashboard.title')}
        description={
          user?.company_name
            ? `${t('hrDashboard.description')} · ${user.company_name}`
            : t('hrDashboard.description')
        }
      />

      {errorMessage ? <ErrorAlert message={errorMessage} /> : null}

      {loading ? (
        <LoadingBlock />
      ) : (
        <>
          <div className="mb-6 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
            <StatCard
              label={t('hrDashboard.employees')}
              value={String(analytics?.total_employees ?? stats.employees)}
            />
            <StatCard
              label={t('hrDashboard.activeOnboarding')}
              value={String(analytics?.active_onboarding ?? stats.activeOnboarding)}
            />
            <StatCard
              label={t('analytics.overdue')}
              value={String(assignmentAnalytics?.overdue ?? analytics?.overdue_count ?? 0)}
            />
            <StatCard
              label={t('hrDashboard.completedOnboarding')}
              value={String(
                assignmentAnalytics?.completed ?? analytics?.completed_onboarding ?? 0,
              )}
            />
            <StatCard
              label={t('hrDashboard.completion')}
              value={
                assignmentAnalytics?.completion_rate != null
                  ? `${assignmentAnalytics.completion_rate}%`
                  : analytics?.completion_rate == null
                    ? t('common.emDash')
                    : `${Math.round(analytics.completion_rate * 100)}%`
              }
            />
            <StatCard
              label={t('hrDashboard.averageProgress')}
              value={
                analytics?.average_progress == null
                  ? t('common.emDash')
                  : `${Math.round(analytics.average_progress)}%`
              }
            />
            <StatCard
              label={t('hrDashboard.notStarted')}
              value={String(analytics?.employees_not_started ?? 0)}
            />
            <StatCard
              label={t('hrDashboard.inProgressEmployees')}
              value={String(analytics?.employees_in_progress ?? 0)}
            />
            <StatCard
              label={t('hrDashboard.completedEmployees')}
              value={String(analytics?.employees_completed ?? 0)}
            />
          </div>

          {analytics?.by_program && analytics.by_program.length > 0 ? (
            <section className="mb-6 overflow-x-auto rounded-lg border border-[var(--color-border)] bg-white">
              <h2 className="px-4 pt-4 text-sm font-semibold">
                {t('hrDashboard.byProgram')}
              </h2>
              <table className="mt-2 min-w-full text-left text-sm">
                <thead className="bg-slate-50 text-xs uppercase text-[var(--color-muted)]">
                  <tr>
                    <th className="px-4 py-2">{t('hrDashboard.program')}</th>
                    <th className="px-4 py-2">{t('hrDashboard.assigned')}</th>
                    <th className="px-4 py-2">{t('hrDashboard.completedOnboarding')}</th>
                    <th className="px-4 py-2">{t('hrDashboard.completion')}</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-[var(--color-border)]">
                  {analytics.by_program.map((row) => (
                    <tr key={row.program_id}>
                      <td className="px-4 py-2">{row.title}</td>
                      <td className="px-4 py-2">{row.assigned}</td>
                      <td className="px-4 py-2">{row.completed}</td>
                      <td className="px-4 py-2">
                        {row.completion_rate == null
                          ? t('common.emDash')
                          : `${Math.round(row.completion_rate * 100)}%`}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </section>
          ) : null}

          {analytics?.completed_over_time && analytics.completed_over_time.length > 0 ? (
            <section className="mb-6 rounded-lg border border-[var(--color-border)] bg-white p-4">
              <h2 className="mb-2 text-sm font-semibold">
                {t('hrDashboard.overTime')}
              </h2>
              <ul className="space-y-1 text-sm text-[var(--color-muted)]">
                {analytics.completed_over_time.map((point) => (
                  <li key={point.date} className="flex justify-between">
                    <span>{point.date}</span>
                    <span>{point.count}</span>
                  </li>
                ))}
              </ul>
            </section>
          ) : null}

          <div className="grid gap-6 lg:grid-cols-3">
            <section className="rounded-lg border border-[var(--color-border)] bg-white p-4">
              <div className="mb-3 flex items-center justify-between">
                <h2 className="text-sm font-semibold">
                  {t('hrDashboard.recentEmployees')}
                </h2>
                <Link
                  to={paths.employees}
                  className="text-xs text-[var(--color-accent)]"
                >
                  {t('companyDashboard.viewAll')}
                </Link>
              </div>
              {recentEmployees.length === 0 ? (
                <EmptyState title={t('hrDashboard.emptyEmployees')} />
              ) : (
                <ul className="space-y-2 text-sm">
                  {recentEmployees.map((e) => (
                    <li key={e.id} className="flex items-center justify-between gap-2">
                      <Link
                        to={paths.employee(e.id)}
                        className="truncate font-medium hover:text-[var(--color-accent)]"
                      >
                        {e.full_name}
                      </Link>
                      <EmployeeStatusBadge status={e.status} />
                    </li>
                  ))}
                </ul>
              )}
            </section>

            <section className="rounded-lg border border-[var(--color-border)] bg-white p-4">
              <div className="mb-3 flex items-center justify-between">
                <h2 className="text-sm font-semibold">
                  {t('hrDashboard.pendingOnboarding')}
                </h2>
                <Link
                  to={paths.assignments}
                  className="text-xs text-[var(--color-accent)]"
                >
                  {t('companyDashboard.viewAll')}
                </Link>
              </div>
              {pendingOnboarding.length === 0 ? (
                <EmptyState title={t('hrDashboard.emptyPending')} />
              ) : (
                <ul className="space-y-2 text-sm">
                  {pendingOnboarding.map((a) => (
                    <li key={a.id} className="flex items-center justify-between gap-2">
                      <Link
                        to={paths.assignment(a.id)}
                        className="truncate hover:text-[var(--color-accent)]"
                      >
                        {employeeName(a.employee_id)} · {titleOf(a)}
                      </Link>
                      <AssignmentStatusBadge status={a.status} />
                    </li>
                  ))}
                </ul>
              )}
            </section>

            <section className="rounded-lg border border-[var(--color-border)] bg-white p-4">
              <div className="mb-3 flex items-center justify-between">
                <h2 className="text-sm font-semibold">
                  {t('hrDashboard.recentProgress')}
                </h2>
                <Link
                  to={paths.progress}
                  className="text-xs text-[var(--color-accent)]"
                >
                  {t('companyDashboard.viewAll')}
                </Link>
              </div>
              {recentProgress.length === 0 ? (
                <EmptyState title={t('hrDashboard.emptyProgress')} />
              ) : (
                <ul className="space-y-2 text-sm">
                  {recentProgress.map((a) => (
                    <li key={a.id} className="flex items-center justify-between gap-2">
                      <Link
                        to={paths.assignment(a.id)}
                        className="truncate hover:text-[var(--color-accent)]"
                      >
                        {employeeName(a.employee_id)} · {titleOf(a)}
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

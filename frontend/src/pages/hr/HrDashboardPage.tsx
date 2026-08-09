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
import { useAssignments } from '../../hooks/useAssignments'
import { useAuth } from '../../hooks/useAuth'
import { useEmployees } from '../../hooks/useEmployees'
import { usePrograms } from '../../hooks/usePrograms'
import { useWorkspacePaths } from '../../hooks/useWorkspacePaths'
import { t } from '../../i18n'
import { isActiveAssignment } from '../../lib/progressUtils'

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
    const invited = staff.filter((e) => e.status === 'invited').length
    const active = assignments.filter(isActiveAssignment).length
    const completed = assignments.filter((a) => a.status === 'completed')
    const countable = assignments.filter((a) => a.status !== 'cancelled')
    const completion =
      countable.length === 0
        ? null
        : Math.round((completed.length / countable.length) * 100)
    return {
      employees: staff.length,
      invited,
      activeOnboarding: active,
      completion,
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

  const loading = employeesLoading || programsLoading || assignmentsLoading
  const errorMessage =
    (employeesError instanceof Error && employeesError.message) ||
    (programsError instanceof Error && programsError.message) ||
    (assignmentsError instanceof Error && assignmentsError.message) ||
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
              value={String(stats.employees)}
            />
            <StatCard
              label={t('hrDashboard.invited')}
              value={String(stats.invited)}
            />
            <StatCard
              label={t('hrDashboard.activeOnboarding')}
              value={String(stats.activeOnboarding)}
            />
            <StatCard
              label={t('hrDashboard.completion')}
              value={
                stats.completion == null ? t('common.emDash') : `${stats.completion}%`
              }
            />
          </div>

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
                        {employeeName(a.employee_id)} · {programTitle(a.program_id)}
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
                        {employeeName(a.employee_id)} · {programTitle(a.program_id)}
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

import { Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import { useMemo } from 'react'
import {
  EmptyState,
  ErrorAlert,
  LoadingBlock,
  PageHeader,
} from '../../components/common/PageHeader'
import { Button } from '../../components/ui/Button'
import { useAuth } from '../../hooks/useAuth'
import { useEmployeeAssignments } from '../../hooks/useEmployeeSelf'
import { useWorkspacePaths } from '../../hooks/useWorkspacePaths'
import { t } from '../../i18n'
import {
  assignmentTitle,
  compareAssignmentsByPriorityDeadline,
  isActiveAssignment,
  isAssignmentOverdue,
} from '../../lib/progressUtils'
import * as assignmentsApi from '../../services/assignmentsApi'
import * as programsApi from '../../services/programsApi'
import { isAcknowledgementAssignment } from '../../types/assignment'

function formatDate(value: string | null | undefined) {
  if (!value) return t('common.emDash')
  try {
    return new Date(value).toLocaleString()
  } catch {
    return value
  }
}

export function EmployeeDashboardPage() {
  const { user } = useAuth()
  const paths = useWorkspacePaths()
  const {
    data: assignments = [],
    isLoading,
    error,
    refetch,
  } = useEmployeeAssignments(user?.id, { activeOnly: true })

  const activeList = useMemo(
    () => assignments.filter(isActiveAssignment).sort(compareAssignmentsByPriorityDeadline),
    [assignments],
  )
  const active = activeList[0] ?? null
  const overdueCount = useMemo(
    () => activeList.filter((a) => isAssignmentOverdue(a)).length,
    [activeList],
  )
  const nextDeadline = useMemo(() => {
    const dated = activeList.filter((a) => a.due_at)
    return dated[0]?.due_at ?? null
  }, [activeList])

  const isAck = active ? isAcknowledgementAssignment(active) : false
  const progressQuery = useQuery({
    queryKey: ['assignment-progress', active?.id],
    queryFn: () => assignmentsApi.getAssignmentProgress(active!.id),
    enabled: Boolean(active?.id) && !isAck,
  })
  const programQuery = useQuery({
    queryKey: ['program', active?.program_id],
    queryFn: () => programsApi.getProgram(active!.program_id!),
    enabled: Boolean(active?.program_id),
  })

  if (isLoading || (active && !isAck && (progressQuery.isLoading || programQuery.isLoading))) {
    return <LoadingBlock />
  }
  if (error) {
    return (
      <ErrorAlert
        message={error instanceof Error ? error.message : t('common.actionFailed')}
        onRetry={() => void refetch()}
      />
    )
  }

  const progress = progressQuery.data
  const program = programQuery.data
  const current = progress?.items.find(
    (item) => item.status !== 'completed' && item.status !== 'skipped',
  )

  return (
    <div>
      <PageHeader
        title={t('employeeDashboard.title')}
        description={
          user?.company_name
            ? `${t('employeeDashboard.description')} · ${user.company_name}`
            : t('employeeDashboard.description')
        }
      />

      <div className="mb-6 grid gap-4 sm:grid-cols-2 lg:grid-cols-4">
        <div className="rounded-lg border border-[var(--color-border)] bg-white px-4 py-4">
          <p className="text-xs uppercase tracking-wide text-[var(--color-muted)]">
            {t('employeeDashboard.activeCount')}
          </p>
          <p className="mt-1 text-2xl font-semibold">{activeList.length}</p>
        </div>
        <div className="rounded-lg border border-[var(--color-border)] bg-white px-4 py-4">
          <p className="text-xs uppercase tracking-wide text-[var(--color-muted)]">
            {t('employeeDashboard.nextDeadline')}
          </p>
          <p className="mt-1 text-sm font-semibold">{formatDate(nextDeadline)}</p>
        </div>
        <div className="rounded-lg border border-[var(--color-border)] bg-white px-4 py-4">
          <p className="text-xs uppercase tracking-wide text-[var(--color-muted)]">
            {t('employeeDashboard.overdue')}
          </p>
          <p
            className={`mt-1 text-2xl font-semibold ${
              overdueCount > 0 ? 'text-[var(--color-danger)]' : ''
            }`}
          >
            {overdueCount}
          </p>
        </div>
        <div className="rounded-lg border border-[var(--color-border)] bg-white px-4 py-4">
          <p className="text-xs uppercase tracking-wide text-[var(--color-muted)]">
            {t('employeeDashboard.currentProgress')}
          </p>
          <p className="mt-1 text-2xl font-semibold">
            {isAck
              ? `${active?.acknowledgement?.percentage ?? 0}%`
              : `${progress?.percentage ?? 0}%`}
          </p>
        </div>
      </div>

      {!active ? (
        <EmptyState
          title={t('employeePortal.noActiveTitle')}
          description={t('employeePortal.noActiveDescription')}
        />
      ) : isAck ? (
        <div className="mb-6 max-w-xl space-y-3 rounded-lg border border-[var(--color-border)] bg-white p-5">
          <p className="text-sm text-[var(--color-muted)]">
            {t('employeePortal.acknowledgementIntro')}
          </p>
          <h2 className="text-lg font-semibold">
            {assignmentTitle(active, () => t('assignments.acknowledgementLabel'))}
          </h2>
          <p className="text-sm">
            {t('assignments.documentsSummary', {
              acked: active.acknowledgement?.acknowledged_required_count ?? 0,
              required: active.acknowledgement?.required_documents ?? 0,
            })}
          </p>
          <Link to={paths.path('/onboarding')}>
            <Button>{t('employeeDashboard.continue')}</Button>
          </Link>
        </div>
      ) : !program ? (
        <EmptyState
          title={t('employeePortal.noActiveTitle')}
          description={t('employeePortal.noActiveDescription')}
        />
      ) : (
        <div className="mb-6 max-w-xl space-y-3 rounded-lg border border-[var(--color-border)] bg-white p-5">
          <p className="text-sm text-[var(--color-muted)]">
            {t('employeePortal.program')}
          </p>
          <h2 className="text-lg font-semibold">{program.title}</h2>
          <p className="text-sm">
            {t('employeePortal.progress')}: {progress?.percentage ?? 0}%
          </p>
          {current ? (
            <p className="text-sm">
              {t('employeePortal.currentStep')}:{' '}
              {current.step?.title ?? t('common.emDash')}
            </p>
          ) : (
            <p className="text-sm text-emerald-700">
              {t('employeePortal.programComplete')}
            </p>
          )}
          <Link to={paths.path('/onboarding')}>
            <Button>{t('employeeDashboard.continue')}</Button>
          </Link>
        </div>
      )}

      <div className="flex flex-wrap gap-3">
        <Link to={paths.path('/onboarding')}>
          <Button variant="secondary">{t('employeeDashboard.goOnboarding')}</Button>
        </Link>
        <Link to={paths.path('/active')}>
          <Button variant="secondary">{t('employeeDashboard.goActive')}</Button>
        </Link>
        <Link to={paths.path('/knowledge')}>
          <Button variant="secondary">{t('nav.knowledgeBase')}</Button>
        </Link>
      </div>
    </div>
  )
}

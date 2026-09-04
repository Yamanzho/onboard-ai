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
import { compareAssignmentsByPriorityDeadline, isActiveAssignment } from '../../lib/progressUtils'
import * as assignmentsApi from '../../services/assignmentsApi'
import * as programsApi from '../../services/programsApi'

export function EmployeeDashboardPage() {
  const { user } = useAuth()
  const paths = useWorkspacePaths()
  const {
    data: assignments = [],
    isLoading,
    error,
    refetch,
  } = useEmployeeAssignments(user?.id, { activeOnly: true })

  const active = useMemo(
    () =>
      assignments
        .filter(isActiveAssignment)
        .sort(compareAssignmentsByPriorityDeadline)[0] ?? null,
    [assignments],
  )

  const progressQuery = useQuery({
    queryKey: ['assignment-progress', active?.id],
    queryFn: () => assignmentsApi.getAssignmentProgress(active!.id),
    enabled: Boolean(active?.id),
  })
  const programQuery = useQuery({
    queryKey: ['program', active?.program_id],
    queryFn: () => programsApi.getProgram(active!.program_id),
    enabled: Boolean(active?.program_id),
  })

  if (isLoading || (active && (progressQuery.isLoading || programQuery.isLoading))) {
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

      {!active || !program ? (
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
        <Link to={paths.path('/ai')}>
          <Button variant="secondary">{t('employeeDashboard.goAI')}</Button>
        </Link>
      </div>
    </div>
  )
}

import { useQuery } from '@tanstack/react-query'
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
import { isActiveAssignment } from '../../lib/progressUtils'
import { t } from '../../i18n'
import * as assignmentsApi from '../../services/assignmentsApi'
import * as programsApi from '../../services/programsApi'
import { Link } from 'react-router-dom'
import { useMemo } from 'react'
import type { ProgressItem } from '../../types/assignment'

export function MyOnboardingPage() {
  const { user } = useAuth()
  const paths = useWorkspacePaths()
  const {
    data: assignments = [],
    isLoading,
    error,
  } = useEmployeeAssignments(user?.id, { activeOnly: true })

  const active = useMemo(
    () =>
      assignments
        .filter(isActiveAssignment)
        .sort(
          (a, b) =>
            new Date(b.assigned_at).getTime() - new Date(a.assigned_at).getTime(),
        )[0] ?? null,
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

  const progress = progressQuery.data
  const program = programQuery.data
  const detailLoading = progressQuery.isLoading || programQuery.isLoading

  if (isLoading || (active && detailLoading)) return <LoadingBlock />
  if (error) {
    return (
      <ErrorAlert
        message={error instanceof Error ? error.message : t('common.actionFailed')}
      />
    )
  }

  if (!active || !progress || !program) {
    return (
      <div>
        <PageHeader
          title={t('employeePortal.myOnboardingTitle')}
          description={t('employeePortal.myOnboardingDescription')}
        />
        <EmptyState
          title={t('employeePortal.noActiveTitle')}
          description={t('employeePortal.noActiveDescription')}
        />
      </div>
    )
  }

  const done = progress.items.filter(
    (i: ProgressItem) => i.status === 'completed' || i.status === 'skipped',
  ).length
  const total = progress.items.length
  const remaining = Math.max(0, total - done)
  const current = progress.items.find(
    (i: ProgressItem) => i.status !== 'completed' && i.status !== 'skipped',
  )

  return (
    <div>
      <PageHeader
        title={t('employeePortal.myOnboardingTitle')}
        description={t('employeePortal.myOnboardingDescription')}
      />
      <div className="max-w-xl space-y-4 rounded-lg border border-[var(--color-border)] bg-white p-5">
        <p className="text-sm text-[var(--color-muted)]">
          {t('employeePortal.program')}
        </p>
        <h2 className="text-lg font-semibold">{program.title}</h2>
        <p className="text-sm">
          {t('employeePortal.progress')}: {done} / {total} ({progress.percentage}
          %)
        </p>
        <p className="text-sm text-[var(--color-muted)]">
          {t('employeePortal.remaining')}: {remaining}
        </p>
        {current ? (
          <div className="rounded-md bg-[var(--color-bg)] p-3 text-sm">
            <p className="font-medium">{t('employeePortal.currentStep')}</p>
            <p>{current.step?.title ?? t('common.emDash')}</p>
          </div>
        ) : (
          <p className="text-sm text-emerald-700">
            {t('employeePortal.programComplete')}
          </p>
        )}
        <Link to={paths.path('/active')}>
          <Button variant="secondary">{t('employeePortal.viewActive')}</Button>
        </Link>
      </div>
    </div>
  )
}

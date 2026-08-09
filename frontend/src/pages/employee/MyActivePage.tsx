import { useQueries } from '@tanstack/react-query'
import {
  EmptyState,
  ErrorAlert,
  LoadingBlock,
  PageHeader,
} from '../../components/common/PageHeader'
import { useAuth } from '../../hooks/useAuth'
import { useEmployeeAssignments } from '../../hooks/useEmployeeSelf'
import { t } from '../../i18n'
import { isActiveAssignment } from '../../lib/progressUtils'
import * as assignmentsApi from '../../services/assignmentsApi'
import * as programsApi from '../../services/programsApi'
import type { AssignmentProgress } from '../../types/assignment'
import type { Program } from '../../types/program'

function formatDate(value: string | null | undefined) {
  if (!value) return t('common.emDash')
  try {
    return new Date(value).toLocaleDateString()
  } catch {
    return value
  }
}

export function MyActivePage() {
  const { user } = useAuth()
  const {
    data: assignments = [],
    isLoading,
    error,
  } = useEmployeeAssignments(user?.id, { activeOnly: true })

  const active = assignments.filter(isActiveAssignment)

  const progressQueries = useQueries({
    queries: active.map((a) => ({
      queryKey: ['assignment-progress', a.id],
      queryFn: () => assignmentsApi.getAssignmentProgress(a.id),
    })),
  })
  const programQueries = useQueries({
    queries: active.map((a) => ({
      queryKey: ['program', a.program_id],
      queryFn: () => programsApi.getProgram(a.program_id),
    })),
  })

  if (
    isLoading ||
    progressQueries.some((q) => q.isLoading) ||
    programQueries.some((q) => q.isLoading)
  ) {
    return <LoadingBlock />
  }
  if (error) {
    return (
      <ErrorAlert
        message={error instanceof Error ? error.message : t('common.actionFailed')}
      />
    )
  }

  return (
    <div>
      <PageHeader
        title={t('employeePortal.activeTitle')}
        description={t('employeePortal.activeDescription')}
      />
      {active.length === 0 ? (
        <EmptyState
          title={t('employeePortal.noActiveTitle')}
          description={t('employeePortal.noActiveDescription')}
        />
      ) : (
        <ul className="space-y-3">
          {active.map((a, index) => {
            const progress = progressQueries[index]?.data as
              | AssignmentProgress
              | undefined
            const program = programQueries[index]?.data as Program | undefined
            return (
              <li
                key={a.id}
                className="rounded-lg border border-[var(--color-border)] bg-white p-4 text-sm"
              >
                <p className="font-semibold">
                  {program?.title ?? a.program_id.slice(0, 8)}
                </p>
                <p className="mt-1 text-[var(--color-muted)]">
                  {t('employeePortal.progress')}:{' '}
                  {progress?.percentage != null ? `${progress.percentage}%` : '…'}
                </p>
                <p className="text-[var(--color-muted)]">
                  {t('employeePortal.started')}:{' '}
                  {formatDate(a.started_at ?? a.assigned_at)}
                </p>
                {a.due_at ? (
                  <p className="text-[var(--color-muted)]">
                    {t('employeePortal.deadline')}: {formatDate(a.due_at)}
                  </p>
                ) : null}
              </li>
            )
          })}
        </ul>
      )}
    </div>
  )
}

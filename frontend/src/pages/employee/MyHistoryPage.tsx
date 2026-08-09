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
import * as programsApi from '../../services/programsApi'

function formatDate(value: string | null | undefined) {
  if (!value) return t('common.emDash')
  try {
    return new Date(value).toLocaleDateString()
  } catch {
    return value
  }
}

export function MyHistoryPage() {
  const { user } = useAuth()
  const {
    data: assignments = [],
    isLoading,
    error,
  } = useEmployeeAssignments(user?.id, { status: 'completed' })

  const programs = useQueries({
    queries: assignments.map((a) => ({
      queryKey: ['program', a.program_id],
      queryFn: () => programsApi.getProgram(a.program_id),
    })),
  })

  if (isLoading || programs.some((q) => q.isLoading)) return <LoadingBlock />
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
        title={t('employeePortal.historyTitle')}
        description={t('employeePortal.historyDescription')}
      />
      {assignments.length === 0 ? (
        <EmptyState
          title={t('employeePortal.historyEmptyTitle')}
          description={t('employeePortal.historyEmptyDescription')}
        />
      ) : (
        <ul className="space-y-3">
          {assignments.map((a, i) => (
            <li
              key={a.id}
              className="rounded-lg border border-[var(--color-border)] bg-white p-4 text-sm"
            >
              <p className="font-semibold">
                {programs[i]?.data?.title ?? a.program_id.slice(0, 8)}
              </p>
              <p className="mt-1 text-[var(--color-muted)]">
                {t('employeePortal.completedAt')}: {formatDate(a.completed_at)}
              </p>
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

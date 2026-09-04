import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useState } from 'react'
import { ErrorAlert } from '../../components/common/PageHeader'
import { Badge } from '../../components/ui/Badge'
import { Button } from '../../components/ui/Button'
import { t } from '../../i18n'
import { ApiError } from '../../services/apiClient'
import * as assignmentsApi from '../../services/assignmentsApi'
import type { Assignment } from '../../types/assignment'

export function AcknowledgementPanel({ assignment }: { assignment: Assignment }) {
  const queryClient = useQueryClient()
  const [openItemId, setOpenItemId] = useState<string | null>(null)
  const [actionError, setActionError] = useState<string | null>(null)

  const listQuery = useQuery({
    queryKey: ['assignment-acknowledgements', assignment.id],
    queryFn: () => assignmentsApi.listAcknowledgements(assignment.id),
  })
  const documentQuery = useQuery({
    queryKey: ['acknowledgement-document', assignment.id, openItemId],
    queryFn: () =>
      assignmentsApi.getAcknowledgementDocument(assignment.id, openItemId!),
    enabled: Boolean(openItemId),
  })
  const acknowledge = useMutation({
    mutationFn: (itemId: string) =>
      assignmentsApi.acknowledgeDocument(assignment.id, itemId),
    onSuccess: async () => {
      await queryClient.invalidateQueries({
        queryKey: ['assignment-acknowledgements'],
      })
      await queryClient.invalidateQueries({ queryKey: ['my-assignments'] })
      await queryClient.invalidateQueries({ queryKey: ['assignment'] })
    },
  })

  const listing = listQuery.data
  const summary = listing?.acknowledgement ?? assignment.acknowledgement
  const items = listing?.items ?? []
  const completed =
    listing?.assignment_status === 'completed' || assignment.status === 'completed'
  const cancelled =
    listing?.assignment_status === 'cancelled' || assignment.status === 'cancelled'
  const canMutate = !completed && !cancelled

  async function onAcknowledge(itemId: string) {
    setActionError(null)
    try {
      await acknowledge.mutateAsync(itemId)
    } catch (err) {
      setActionError(
        err instanceof ApiError ? err.message : t('employeePortal.acknowledgeFailed'),
      )
    }
  }

  if (listQuery.isLoading) {
    return <p className="text-sm text-[var(--color-muted)]">{t('common.loading')}</p>
  }
  if (listQuery.error) {
    return (
      <ErrorAlert
        message={t('common.actionFailed')}
        onRetry={() => void listQuery.refetch()}
      />
    )
  }

  return (
    <div className="space-y-4">
      <p className="text-sm text-[var(--color-muted)]">
        {t('employeePortal.acknowledgementIntro')}
      </p>
      <h2 className="text-lg font-semibold">
        {summary?.title ?? t('assignments.acknowledgementLabel')}
      </h2>
      <p className="text-sm">
        {t('assignments.documentsSummary', {
          acked: summary?.acknowledged_required_count ?? 0,
          required: summary?.required_documents ?? 0,
        })}
      </p>
      {completed ? (
        <p className="rounded-md bg-emerald-50 px-3 py-2 text-sm text-emerald-800">
          {t('employeePortal.acknowledgementComplete')}
        </p>
      ) : null}

      <ol className="space-y-3">
        {items.map((item, index) => {
          const open = openItemId === item.id
          return (
            <li
              key={item.id}
              className="rounded-md border border-[var(--color-border)] bg-[var(--color-bg)] p-4"
            >
              <p className="text-xs uppercase tracking-wide text-[var(--color-muted)]">
                {t('employeePortal.documentIndex', {
                  current: index + 1,
                  total: items.length,
                })}
                {' · '}
                {item.is_required
                  ? t('assignments.documentRequired')
                  : t('assignments.documentOptional')}
                {' · '}
                {t('employeePortal.versionLabel', { version: item.version })}
              </p>
              <h3 className="mt-1 font-semibold">{item.title}</h3>
              <div className="mt-2 flex flex-wrap items-center gap-2">
                <Badge tone={item.acknowledged_at ? 'success' : 'neutral'}>
                  {item.acknowledged_at
                    ? t('assignments.acknowledgedYes')
                    : t('assignments.acknowledgedNo')}
                </Badge>
                {item.acknowledged_at ? (
                  <span className="text-xs text-[var(--color-muted)]">
                    {new Date(item.acknowledged_at).toLocaleString()}
                  </span>
                ) : null}
              </div>
              <div className="mt-3 flex flex-wrap gap-2">
                <Button
                  type="button"
                  variant="secondary"
                  onClick={() => setOpenItemId(open ? null : item.id)}
                >
                  {open
                    ? t('employeePortal.closeDocument')
                    : t('employeePortal.openDocument')}
                </Button>
                {canMutate && !item.acknowledged_at ? (
                  <Button
                    type="button"
                    disabled={acknowledge.isPending}
                    onClick={() => void onAcknowledge(item.id)}
                  >
                    {t('assignments.acknowledgeAction')}
                  </Button>
                ) : null}
              </div>
              {open ? (
                <div className="mt-3 whitespace-pre-wrap text-sm">
                  {documentQuery.isLoading
                    ? t('common.loading')
                    : documentQuery.data?.body ?? t('common.emDash')}
                </div>
              ) : null}
            </li>
          )
        })}
      </ol>
      {actionError ? <ErrorAlert message={actionError} /> : null}
    </div>
  )
}

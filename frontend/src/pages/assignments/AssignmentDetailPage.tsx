import { Link, useParams } from 'react-router-dom'
import { useState, type ReactNode } from 'react'
import {
  EmptyState,
  ErrorAlert,
  LoadingBlock,
  PageHeader,
} from '../../components/common/PageHeader'
import { AssignmentStatusBadge } from '../../components/assignments/AssignmentStatusBadge'
import { AssignmentPriorityBadge } from '../../components/assignments/AssignmentPriorityBadge'
import { Badge } from '../../components/ui/Badge'
import { Button } from '../../components/ui/Button'
import {
  useAssignment,
  useAssignmentAcknowledgements,
  useAssignmentMutations,
  useAssignmentNotifications,
  useAssignmentProgress,
} from '../../hooks/useAssignments'
import { useEmployee } from '../../hooks/useEmployees'
import { useProgram } from '../../hooks/usePrograms'
import { useCapabilities } from '../../hooks/useCapabilities'
import { useWorkspacePaths } from '../../hooks/useWorkspacePaths'
import { CAPABILITIES } from '../../lib/capabilities'
import { labelAssignmentType, labelProgressStatus, labelReminderMode, labelNotificationKind, labelOutboundStatus, labelStepType, t } from '../../i18n'
import { ApiError } from '../../services/apiClient'
import { assignmentTitle, isAssignmentOverdue } from '../../lib/progressUtils'
import { isAcknowledgementAssignment } from '../../types/assignment'
import { parseQuizAttemptSummary, quizScoreLabel } from '../../lib/quizUtils'

function formatDate(value: string | null | undefined) {
  if (!value) return t('common.emDash')
  try {
    return new Date(value).toLocaleString()
  } catch {
    return value
  }
}

function progressTone(status: string) {
  if (status === 'completed') return 'success' as const
  if (status === 'in_progress') return 'warning' as const
  if (status === 'skipped') return 'neutral' as const
  return 'neutral' as const
}

export function AssignmentDetailPage() {
  const { assignmentId } = useParams<{ assignmentId: string }>()
  const paths = useWorkspacePaths()
  const { can } = useCapabilities()
  const canManage = can(CAPABILITIES.ASSIGNMENTS_MANAGE)
  const { data: assignment, isLoading, error } = useAssignment(assignmentId)
  const isAck = assignment ? isAcknowledgementAssignment(assignment) : false
  const { data: progress, isLoading: progressLoading } =
    useAssignmentProgress(isAck ? undefined : assignmentId)
  const { data: acknowledgements, isLoading: acknowledgementsLoading } =
    useAssignmentAcknowledgements(isAck ? assignmentId : undefined)
  const { data: notifications, isLoading: notificationsLoading } =
    useAssignmentNotifications(assignmentId)
  const { data: employee } = useEmployee(assignment?.employee_id)
  const { data: program } = useProgram(assignment?.program_id ?? undefined)
  const { data: assigner } = useEmployee(assignment?.assigned_by_id ?? undefined)
  const { cancel, remindNow } = useAssignmentMutations()
  const [actionError, setActionError] = useState<string | null>(null)
  const [remindOk, setRemindOk] = useState<string | null>(null)

  async function onRemindNow() {
    if (!assignment) return
    if (notifications?.preference.mode === 'disabled') return
    setActionError(null)
    setRemindOk(null)
    try {
      await remindNow.mutateAsync(assignment.id)
      setRemindOk(t('assignments.remindNowOk'))
    } catch (err) {
      setActionError(
        err instanceof ApiError ? err.message : t('assignments.remindNowFailed'),
      )
    }
  }

  async function onCancel() {
    if (!assignment) return
    const ok = window.confirm(t('assignments.cancelConfirm'))
    if (!ok) return
    setActionError(null)
    try {
      await cancel.mutateAsync(assignment.id)
    } catch (err) {
      setActionError(
        err instanceof ApiError ? err.message : t('assignments.cancelFailed'),
      )
    }
  }

  if (isLoading) return <LoadingBlock />
  if (error || !assignment) {
    return (
      <ErrorAlert
        message={
          error instanceof Error ? error.message : t('assignments.notFound')
        }
      />
    )
  }

  const items = progress?.items ?? []
  const canCancel =
    canManage &&
    (assignment.status === 'pending' || assignment.status === 'in_progress')
  const remindersDisabled = notifications?.preference.mode === 'disabled'
  const overdue = isAssignmentOverdue(assignment)

  const rows: { label: string; value: ReactNode }[] = [
    {
      label: t('assignments.employee'),
      value: (
        <Link
          to={paths.employee(assignment.employee_id)}
          className="text-[var(--color-accent)] hover:underline"
        >
          {employee?.full_name ?? assignment.employee_id}
        </Link>
      ),
    },
    {
      label: t('assignments.assignmentType'),
      value: labelAssignmentType(assignment.assignment_type ?? 'program'),
    },
    {
      label: t('assignments.program'),
      value: isAck ? (
        assignment.acknowledgement?.title ?? t('assignments.acknowledgementLabel')
      ) : assignment.program_id ? (
        <Link
          to={paths.program(assignment.program_id)}
          className="text-[var(--color-accent)] hover:underline"
        >
          {program?.title ?? assignment.program_id}
        </Link>
      ) : (
        t('common.emDash')
      ),
    },
    ...(isAck
      ? []
      : [
          {
            label: t('assignments.programRevision'),
            value: `v${assignment.program_revision ?? program?.revision ?? 1}`,
          },
        ]),
    {
      label: t('assignments.progress'),
      value: isAck
        ? acknowledgementsLoading
          ? '…'
          : t('assignments.documentsSummary', {
              acked:
                acknowledgements?.acknowledgement.acknowledged_required_count ??
                assignment.acknowledgement?.acknowledged_required_count ??
                0,
              required:
                acknowledgements?.acknowledgement.required_documents ??
                assignment.acknowledgement?.required_documents ??
                0,
            })
        : progressLoading
          ? '…'
          : `${progress?.percentage ?? 0}%`,
    },
    {
      label: t('assignments.assignedBy'),
      value: assigner?.full_name ?? t('common.emDash'),
    },
    { label: t('assignments.dueDate'), value: formatDate(assignment.due_at) },
    {
      label: t('assignments.priority'),
      value: <AssignmentPriorityBadge priority={assignment.priority} />,
    },
    { label: t('assignments.assignedAt'), value: formatDate(assignment.assigned_at) },
    { label: t('assignments.startedAt'), value: formatDate(assignment.started_at) },
    {
      label: t('assignments.completedAt'),
      value: formatDate(assignment.completed_at),
    },
    { label: t('common.created'), value: formatDate(assignment.created_at) },
    { label: t('common.updated'), value: formatDate(assignment.updated_at) },
    { label: t('assignments.assignmentId'), value: assignment.id },
    {
      label: t('assignments.reminderState'),
      value: labelReminderMode(notifications?.preference.mode ?? 'default'),
    },
    {
      label: t('assignments.lastAcknowledged'),
      value: formatDate(notifications?.preference.last_acknowledged_at),
    },
  ]

  return (
    <div>
      <PageHeader
        title={
          assignmentTitle(assignment, (id) => program?.title ?? id) ??
          t('assignments.title')
        }
        description={t('assignments.detailDescription')}
        action={
          <div className="flex flex-wrap gap-2">
            <Link to={paths.assignments}>
              <Button variant="secondary">{t('assignments.backToList')}</Button>
            </Link>
            {canCancel ? (
              <Button
                variant="secondary"
                disabled={remindNow.isPending || remindersDisabled}
                title={
                  remindersDisabled ? t('assignments.remindNowDisabled') : undefined
                }
                onClick={() => void onRemindNow()}
              >
                {remindNow.isPending
                  ? t('assignments.reminding')
                  : t('assignments.remindNow')}
              </Button>
            ) : null}
            {canCancel ? (
              <Button
                variant="danger"
                disabled={cancel.isPending}
                onClick={() => void onCancel()}
              >
                {cancel.isPending
                  ? t('assignments.cancelling')
                  : t('assignments.cancelAssignment')}
              </Button>
            ) : null}
          </div>
        }
      />

      {actionError ? <ErrorAlert message={actionError} /> : null}
      {remindOk ? (
        <div className="mb-4 rounded-md border border-emerald-200 bg-emerald-50 px-3 py-2 text-sm text-emerald-800">
          {remindOk}
        </div>
      ) : null}
      {remindersDisabled ? (
        <div className="mb-4 rounded-md border border-[var(--color-border)] bg-slate-50 px-3 py-2 text-sm text-[var(--color-muted)]">
          {t('assignments.remindNowDisabled')}
        </div>
      ) : null}

      <div className="mb-4 flex flex-wrap items-center gap-3 rounded-lg border border-[var(--color-border)] bg-white px-4 py-3 text-sm">
        <AssignmentStatusBadge status={assignment.status} />
        <AssignmentPriorityBadge priority={assignment.priority} />
        {overdue ? (
          <span className="text-xs font-medium text-[var(--color-danger)]">
            {t('assignments.overdue')}
          </span>
        ) : null}
        <span className="text-[var(--color-muted)]">
          {employee?.full_name ?? t('assignments.employee')}
        </span>
      </div>

      <div className="mb-6 overflow-hidden rounded-lg border border-[var(--color-border)] bg-white">
        <dl className="divide-y divide-[var(--color-border)]">
          {rows.map((row) => (
            <div
              key={row.label}
              className="grid gap-1 px-4 py-3 sm:grid-cols-[12rem_1fr] sm:gap-4"
            >
              <dt className="text-sm text-[var(--color-muted)]">{row.label}</dt>
              <dd className="break-all text-sm font-medium">{row.value}</dd>
            </div>
          ))}
        </dl>
      </div>

      {isAck ? (
      <div>
        <h2 className="mb-3 text-lg font-semibold">{t('assignments.documents')}</h2>
        {acknowledgementsLoading ? (
          <LoadingBlock label={t('assignments.loadingProgress')} />
        ) : !acknowledgements || acknowledgements.items.length === 0 ? (
          <EmptyState
            title={t('assignments.emptyProgressTitle')}
            description={t('assignments.emptyProgressDescription')}
          />
        ) : (
          <div className="overflow-hidden rounded-lg border border-[var(--color-border)] bg-white">
            <table className="min-w-full text-left text-sm">
              <thead className="bg-slate-50 text-xs uppercase text-[var(--color-muted)]">
                <tr>
                  <th className="px-4 py-3">{t('programs.steps.colNumber')}</th>
                  <th className="px-4 py-3">{t('assignments.documents')}</th>
                  <th className="px-4 py-3">{t('assignments.colVersion')}</th>
                  <th className="px-4 py-3">{t('common.status')}</th>
                  <th className="px-4 py-3">{t('assignments.colAcknowledged')}</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-[var(--color-border)]">
                {acknowledgements.items.map((item) => (
                  <tr key={item.id}>
                    <td className="px-4 py-3 text-[var(--color-muted)]">{item.position}</td>
                    <td className="px-4 py-3 font-medium">
                      {item.title}
                      <span className="ml-2 text-xs text-[var(--color-muted)]">
                        {item.is_required
                          ? t('assignments.documentRequired')
                          : t('assignments.documentOptional')}
                      </span>
                    </td>
                    <td className="px-4 py-3">v{item.version}</td>
                    <td className="px-4 py-3">
                      <Badge tone={item.acknowledged_at ? 'success' : 'neutral'}>
                        {item.acknowledged_at
                          ? t('assignments.acknowledgedYes')
                          : t('assignments.acknowledgedNo')}
                      </Badge>
                    </td>
                    <td className="px-4 py-3 text-[var(--color-muted)]">
                      {formatDate(item.acknowledged_at)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
      ) : (
      <div>
        <h2 className="mb-3 text-lg font-semibold">{t('assignments.steps')}</h2>
        {progressLoading ? (
          <LoadingBlock label={t('assignments.loadingProgress')} />
        ) : items.length === 0 ? (
          <EmptyState
            title={t('assignments.emptyProgressTitle')}
            description={t('assignments.emptyProgressDescription')}
          />
        ) : (
          <div className="overflow-hidden rounded-lg border border-[var(--color-border)] bg-white">
            <table className="min-w-full text-left text-sm">
              <thead className="bg-slate-50 text-xs uppercase text-[var(--color-muted)]">
                <tr>
                  <th className="px-4 py-3">{t('programs.steps.colNumber')}</th>
                  <th className="px-4 py-3">{t('assignments.colStep')}</th>
                  <th className="px-4 py-3">{t('assignments.colType')}</th>
                  <th className="px-4 py-3">{t('common.status')}</th>
                  <th className="px-4 py-3">{t('assignments.colCompleted')}</th>
                  <th className="px-4 py-3">{t('assignments.colPayload')}</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-[var(--color-border)]">
                {items.map((item, index) => {
                  const step = item.step
                  return (
                    <tr key={item.id}>
                      <td className="px-4 py-3 text-[var(--color-muted)]">
                        {(step?.position ?? index) + 1}
                      </td>
                      <td className="px-4 py-3 font-medium">
                        {step?.title ?? item.step_id.slice(0, 8)}
                      </td>
                      <td className="px-4 py-3">
                        <Badge>
                          {step?.step_type
                            ? labelStepType(step.step_type)
                            : t('common.emDash')}
                        </Badge>
                      </td>
                      <td className="px-4 py-3">
                        <Badge tone={progressTone(item.status)}>
                          {labelProgressStatus(item.status)}
                        </Badge>
                      </td>
                      <td className="px-4 py-3 text-[var(--color-muted)]">
                        {formatDate(item.completed_at)}
                      </td>
                      <td className="max-w-xs px-4 py-3 text-xs text-[var(--color-muted)]">
                        {(() => {
                          const summary = parseQuizAttemptSummary(item.payload)
                          const label = quizScoreLabel(item.payload)
                          if (summary.attempt_count != null || label) {
                            return (
                              <div className="space-y-1">
                                {label ? (
                                  <div>
                                    {t('assignments.quizScore')}: {label}
                                  </div>
                                ) : null}
                                {summary.best_score != null ? (
                                  <div>
                                    {t('assignments.quizBestScore')}: {summary.best_score}%
                                  </div>
                                ) : null}
                                {summary.last_score != null &&
                                summary.last_score !== summary.best_score ? (
                                  <div>
                                    {t('assignments.quizLastScore')}: {summary.last_score}%
                                  </div>
                                ) : null}
                                {summary.attempt_count != null ? (
                                  <div>
                                    {t('assignments.quizAttempts')}: {summary.attempt_count}
                                  </div>
                                ) : null}
                                {summary.last_attempt_at ? (
                                  <div>
                                    {t('assignments.quizLastAttempt')}:{' '}
                                    {formatDate(summary.last_attempt_at)}
                                  </div>
                                ) : null}
                              </div>
                            )
                          }
                          return t('common.emDash')
                        })()}
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>
      )}

      <div className="mt-8">
        <h2 className="mb-3 text-lg font-semibold">
          {t('assignments.notificationsTitle')}
        </h2>
        {notificationsLoading ? (
          <LoadingBlock label={t('assignments.loadingProgress')} />
        ) : !notifications || notifications.items.length === 0 ? (
          <EmptyState
            title={t('assignments.notificationsEmpty')}
            description={t('assignments.notificationsEmpty')}
          />
        ) : (
          <div className="overflow-hidden rounded-lg border border-[var(--color-border)] bg-white">
            <table className="min-w-full text-left text-sm">
              <thead className="bg-slate-50 text-xs uppercase text-[var(--color-muted)]">
                <tr>
                  <th className="px-4 py-3">{t('assignments.colWhen')}</th>
                  <th className="px-4 py-3">{t('assignments.colKind')}</th>
                  <th className="px-4 py-3">{t('assignments.colDelivery')}</th>
                  <th className="px-4 py-3">{t('assignments.colPreview')}</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-[var(--color-border)]">
                {notifications.items.map((item) => (
                  <tr key={item.id}>
                    <td className="px-4 py-3 text-[var(--color-muted)]">
                      {formatDate(item.created_at)}
                    </td>
                    <td className="px-4 py-3">
                      {labelNotificationKind(item.source_type)}
                    </td>
                    <td className="px-4 py-3">
                      {labelOutboundStatus(item.status)}
                    </td>
                    <td className="max-w-sm truncate px-4 py-3 text-xs text-[var(--color-muted)]">
                      {item.preview}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </div>
    </div>
  )
}

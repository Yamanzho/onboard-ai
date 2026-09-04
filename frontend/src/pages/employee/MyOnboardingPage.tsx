import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useMemo, useState } from 'react'
import {
  EmptyState,
  ErrorAlert,
  LoadingBlock,
  PageHeader,
} from '../../components/common/PageHeader'
import { parseQuizQuestions } from '../../components/onboarding/stepFormUtils'
import { Button } from '../../components/ui/Button'
import { Input, Label, Textarea } from '../../components/ui/Field'
import { useAuth } from '../../hooks/useAuth'
import { useEmployeeAssignments } from '../../hooks/useEmployeeSelf'
import { labelStepType, t } from '../../i18n'
import { compareAssignmentsByPriorityDeadline, isActiveAssignment } from '../../lib/progressUtils'
import { isAcknowledgementAssignment } from '../../types/assignment'
import { AcknowledgementPanel } from './AcknowledgementPanel'
import {
  isStructuredQuizContent,
  parseEmployeeQuizQuestions,
  parseQuizAttemptSummary,
  quizScoreLabel,
} from '../../lib/quizUtils'
import { ApiError } from '../../services/apiClient'
import * as assignmentsApi from '../../services/assignmentsApi'
import * as programsApi from '../../services/programsApi'
import type { ProgressItem } from '../../types/assignment'

const DONE = new Set(['completed', 'skipped'])

function stepBody(item: ProgressItem): string {
  const content = item.step?.content
  if (!content) return ''
  const blocks = content.blocks
  if (Array.isArray(blocks) && blocks.length > 0) {
    const texts = blocks
      .map((block) => {
        if (!block || typeof block !== 'object') return ''
        const rec = block as Record<string, unknown>
        const text = rec.text ?? rec.body
        return typeof text === 'string' ? text.trim() : ''
      })
      .filter(Boolean)
    if (texts.length > 0) return texts.join('\n\n')
  }
  const body = content.body ?? content.text
  return typeof body === 'string' ? body : ''
}

function stepUrl(item: ProgressItem): string | null {
  const content = item.step?.content
  if (!content) return null
  const url = content.url ?? content.link
  return typeof url === 'string' && url.trim() ? url.trim() : null
}

export function MyOnboardingPage() {
  const { user } = useAuth()
  const queryClient = useQueryClient()
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

  const complete = useMutation({
    mutationFn: ({
      progressId,
      payload,
    }: {
      progressId: string
      payload?: Record<string, unknown>
    }) => assignmentsApi.completeProgress(progressId, payload),
    onSuccess: async () => {
      await queryClient.invalidateQueries({ queryKey: ['assignment-progress'] })
      await queryClient.invalidateQueries({ queryKey: ['my-assignments'] })
    },
  })

  const [ack, setAck] = useState(false)
  const [answers, setAnswers] = useState<Record<string, string>>({})
  const [optionAnswers, setOptionAnswers] = useState<Record<string, string[]>>({})
  const [actionError, setActionError] = useState<string | null>(null)

  const progress = progressQuery.data
  const program = programQuery.data
  const detailLoading = isAck
    ? false
    : progressQuery.isLoading || programQuery.isLoading

  if (isLoading || (active && detailLoading)) return <LoadingBlock />
  if (error) {
    return (
      <ErrorAlert
        message={error instanceof Error ? error.message : t('common.actionFailed')}
        onRetry={() => void refetch()}
      />
    )
  }
  if (!isAck && (progressQuery.error || programQuery.error)) {
    return (
      <ErrorAlert
        message={t('common.actionFailed')}
        onRetry={() => {
          void progressQuery.refetch()
          void programQuery.refetch()
        }}
      />
    )
  }

  if (active && isAck) {
    return (
      <div>
        <PageHeader
          title={t('employeePortal.myOnboardingTitle')}
          description={t('employeePortal.myOnboardingDescription')}
        />
        <div className="max-w-2xl rounded-lg border border-[var(--color-border)] bg-white p-5">
          <AcknowledgementPanel assignment={active} />
        </div>
      </div>
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

  const ordered = [...progress.items].sort((a, b) => {
    const pa = a.step?.position ?? 0
    const pb = b.step?.position ?? 0
    return pa - pb
  })
  const done = ordered.filter((i) => DONE.has(i.status)).length
  const total = ordered.length
  const remaining = Math.max(0, total - done)
  const current = ordered.find((i) => !DONE.has(i.status)) ?? null
  const completeProgram = current === null
  const stepType = current?.step?.step_type ?? 'content'
  const currentContent = current?.step?.content
  const structuredQuiz = Boolean(
    current &&
      stepType === 'quiz' &&
      isStructuredQuizContent(currentContent),
  )
  const questions = current && !structuredQuiz
    ? parseQuizQuestions(current.step?.content)
    : []
  const structuredQuestions = current && structuredQuiz
    ? parseEmployeeQuizQuestions(currentContent)
    : []
  const currentSummary = current
    ? parseQuizAttemptSummary(current.payload)
    : null

  async function onComplete() {
    if (!current) return
    setActionError(null)
    let payload: Record<string, unknown> = { source: 'web' }
    if (stepType === 'ack') {
      if (!ack) {
        setActionError(t('employeePortal.ackRequired'))
        return
      }
      payload = { ...payload, ack: true }
    }
    if (stepType === 'quiz' && structuredQuiz) {
      const missing = structuredQuestions.filter(
        (q) => (optionAnswers[q.id] ?? []).length === 0,
      )
      if (missing.length > 0) {
        setActionError(t('employeePortal.quizRequired'))
        return
      }
      payload = {
        ...payload,
        answers: structuredQuestions.map((q) => ({
          question_id: q.id,
          selected_option_ids: optionAnswers[q.id] ?? [],
        })),
      }
    } else if (stepType === 'quiz') {
      const missing = questions.filter((q) => !answers[q.id]?.trim())
      if (missing.length > 0) {
        setActionError(t('employeePortal.quizRequired'))
        return
      }
      payload = {
        ...payload,
        answers: Object.fromEntries(
          questions.map((q) => [q.id, answers[q.id]?.trim() ?? '']),
        ),
      }
    }
    try {
      await complete.mutateAsync({ progressId: current.id, payload })
      setAck(false)
      setAnswers({})
      setOptionAnswers({})
    } catch (err) {
      setActionError(
        err instanceof ApiError ? err.message : t('employeePortal.completeFailed'),
      )
    }
  }

  return (
    <div>
      <PageHeader
        title={t('employeePortal.myOnboardingTitle')}
        description={t('employeePortal.myOnboardingDescription')}
      />
      <div className="max-w-2xl space-y-4 rounded-lg border border-[var(--color-border)] bg-white p-5">
        <p className="text-sm text-[var(--color-muted)]">
          {t('employeePortal.program')}
        </p>
        <h2 className="text-lg font-semibold">{program.title}</h2>
        <p className="text-sm">
          {t('employeePortal.progress')}: {done} / {total} ({progress.percentage}
          %)
        </p>
        <div
          className="h-2 overflow-hidden rounded-full bg-slate-100"
          role="progressbar"
          aria-valuenow={progress.percentage}
          aria-valuemin={0}
          aria-valuemax={100}
        >
          <div
            className="h-full bg-[var(--color-accent)]"
            style={{ width: `${Math.min(100, Math.max(0, progress.percentage))}%` }}
          />
        </div>
        <p className="text-sm text-[var(--color-muted)]">
          {t('employeePortal.remaining')}: {remaining}
        </p>

        <ol className="space-y-2 text-sm">
          {ordered.map((item, index) => (
            <li key={item.id} className="flex items-start justify-between gap-3">
              <span>
                {index + 1}. {item.step?.title ?? t('dashboard.stepFallback')}
              </span>
              <span className="shrink-0 text-[var(--color-muted)]">
                {(() => {
                  const label = quizScoreLabel(item.payload)
                  const summary = parseQuizAttemptSummary(item.payload)
                  if (DONE.has(item.status)) {
                    return label
                      ? `${t('employeePortal.stepDone')} · ${label}`
                      : t('employeePortal.stepDone')
                  }
                  if (summary.attempt_count) {
                    return `${t('employeePortal.stepOpen')} · ${t('employeePortal.quizAttempts')}: ${summary.attempt_count}`
                  }
                  return t('employeePortal.stepOpen')
                })()}
              </span>
            </li>
          ))}
        </ol>

        {completeProgram ? (
          <p className="rounded-md bg-emerald-50 px-3 py-2 text-sm text-emerald-800">
            {t('employeePortal.programComplete')}
          </p>
        ) : current ? (
          <div className="space-y-3 rounded-md border border-[var(--color-border)] bg-[var(--color-bg)] p-4">
            <p className="text-xs uppercase tracking-wide text-[var(--color-muted)]">
              {t('employeePortal.currentStep')} · {labelStepType(stepType)}
            </p>
            <h3 className="font-semibold">{current.step?.title}</h3>
            {current.step?.description ? (
              <p className="whitespace-pre-wrap text-sm">{current.step.description}</p>
            ) : null}
            {stepBody(current) ? (
              <p className="whitespace-pre-wrap text-sm">{stepBody(current)}</p>
            ) : null}
            {stepUrl(current) ? (
              <a
                href={stepUrl(current)!}
                target="_blank"
                rel="noreferrer"
                className="inline-block text-sm text-[var(--color-accent)] underline"
              >
                {stepUrl(current)}
              </a>
            ) : null}

            {stepType === 'ack' ? (
              <label className="flex items-center gap-2 text-sm">
                <input
                  type="checkbox"
                  checked={ack}
                  onChange={(e) => setAck(e.target.checked)}
                />
                {t('employeePortal.ackLabel')}
              </label>
            ) : null}

            {stepType === 'quiz' && currentSummary?.attempt_count ? (
              <div className="rounded-md bg-slate-50 px-3 py-2 text-sm">
                <p>
                  {t('employeePortal.quizAttempts')}: {currentSummary.attempt_count}
                  {currentSummary.last_score != null
                    ? ` · ${t('employeePortal.quizLastScore')}: ${currentSummary.last_score}%`
                    : ''}
                  {currentSummary.best_score != null
                    ? ` · ${t('employeePortal.quizBestScore')}: ${currentSummary.best_score}%`
                    : ''}
                </p>
                {currentSummary.passed ? (
                  <p>{t('employeePortal.quizPassedHint')}</p>
                ) : (
                  <p>{t('employeePortal.quizFailedHint')}</p>
                )}
              </div>
            ) : null}

            {stepType === 'quiz' && structuredQuiz ? (
              <div className="space-y-3">
                {structuredQuestions.map((question, index) => {
                  const multiple = question.type === 'multiple_choice'
                  const selected = optionAnswers[question.id] ?? []
                  return (
                    <div key={question.id}>
                      <p className="mb-2 text-sm font-medium">
                        {index + 1}. {question.text}
                      </p>
                      <div className="space-y-2">
                        {(question.options ?? []).map((option) => (
                          <label
                            key={option.id}
                            className="flex items-center gap-2 text-sm"
                          >
                            <input
                              type={multiple ? 'checkbox' : 'radio'}
                              name={`q-${question.id}`}
                              checked={selected.includes(option.id)}
                              onChange={() => {
                                setOptionAnswers((prev) => {
                                  const currentIds = prev[question.id] ?? []
                                  if (!multiple) {
                                    return { ...prev, [question.id]: [option.id] }
                                  }
                                  const next = currentIds.includes(option.id)
                                    ? currentIds.filter((id) => id !== option.id)
                                    : [...currentIds, option.id]
                                  return { ...prev, [question.id]: next }
                                })
                              }}
                            />
                            {option.text}
                          </label>
                        ))}
                      </div>
                    </div>
                  )
                })}
              </div>
            ) : null}

            {stepType === 'quiz' && !structuredQuiz ? (
              <div className="space-y-3">
                {questions.map((question, index) => (
                  <div key={question.id}>
                    <Label htmlFor={`q-${question.id}`}>
                      {index + 1}. {question.text}
                    </Label>
                    {question.text.length > 80 ? (
                      <Textarea
                        id={`q-${question.id}`}
                        rows={2}
                        value={answers[question.id] ?? ''}
                        onChange={(e) =>
                          setAnswers((prev) => ({
                            ...prev,
                            [question.id]: e.target.value,
                          }))
                        }
                      />
                    ) : (
                      <Input
                        id={`q-${question.id}`}
                        value={answers[question.id] ?? ''}
                        onChange={(e) =>
                          setAnswers((prev) => ({
                            ...prev,
                            [question.id]: e.target.value,
                          }))
                        }
                      />
                    )}
                  </div>
                ))}
              </div>
            ) : null}

            {actionError ? <ErrorAlert message={actionError} /> : null}
            <Button
              type="button"
              disabled={complete.isPending}
              onClick={() => void onComplete()}
            >
              {complete.isPending
                ? t('employeePortal.completing')
                : stepType === 'ack'
                  ? t('employeePortal.confirmAck')
                  : stepType === 'task'
                    ? t('employeePortal.markTask')
                    : stepType === 'quiz'
                      ? t('employeePortal.submitQuiz')
                      : t('employeePortal.markRead')}
            </Button>
          </div>
        ) : null}
      </div>
    </div>
  )
}

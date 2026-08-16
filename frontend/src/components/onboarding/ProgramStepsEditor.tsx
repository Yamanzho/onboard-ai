import { useState } from 'react'
import {
  EmptyState,
  ErrorAlert,
  LoadingBlock,
} from '../common/PageHeader'
import { Badge } from '../ui/Badge'
import { Button } from '../ui/Button'
import {
  useProgramSteps,
  useStepMutations,
} from '../../hooks/usePrograms'
import { labelStepType, t } from '../../i18n'
import { ApiError } from '../../services/apiClient'
import type { Step, StepType } from '../../types/step'
import {
  StepForm,
} from './StepForm'
import {
  buildStepContent,
  stepContentBody,
  stepContentQuestions,
  stepContentUrl,
  type StepFormValues,
} from './stepFormUtils'

const emptyForm: StepFormValues = {
  title: '',
  description: '',
  step_type: 'content',
  content_body: '',
  content_url: '',
  content_questions: '',
  is_required: true,
  estimated_minutes: '',
}

function toPayload(values: StepFormValues, existingContent?: Record<string, unknown>) {
  return {
    title: values.title,
    description: values.description || null,
    step_type: values.step_type,
    content: buildStepContent(values, existingContent),
    is_required: values.is_required,
    estimated_minutes: values.estimated_minutes
      ? Number(values.estimated_minutes)
      : null,
  }
}

interface ProgramStepsEditorProps {
  programId: string
  readOnly?: boolean
}

export function ProgramStepsEditor({
  programId,
  readOnly = false,
}: ProgramStepsEditorProps) {
  const { data, isLoading, error } = useProgramSteps(programId)
  const { create, update, remove, reorder } = useStepMutations(programId)
  const [actionError, setActionError] = useState<string | null>(null)
  const [showCreate, setShowCreate] = useState(false)
  const [editing, setEditing] = useState<Step | null>(null)

  const steps = data ?? []

  async function onCreate(values: StepFormValues) {
    setActionError(null)
    try {
      await create.mutateAsync(toPayload(values))
      setShowCreate(false)
    } catch (err) {
      throw new Error(
        err instanceof ApiError ? err.message : t('programs.steps.createFailed'),
      )
    }
  }

  async function onUpdate(values: StepFormValues) {
    if (!editing) return
    setActionError(null)
    try {
      await update.mutateAsync({
        id: editing.id,
        payload: toPayload(values, editing.content),
      })
      setEditing(null)
    } catch (err) {
      throw new Error(
        err instanceof ApiError ? err.message : t('programs.steps.updateFailed'),
      )
    }
  }

  async function onDelete(step: Step) {
    const ok = window.confirm(
      t('programs.steps.deleteConfirm', { title: step.title }),
    )
    if (!ok) return
    setActionError(null)
    try {
      await remove.mutateAsync(step.id)
    } catch (err) {
      setActionError(
        err instanceof ApiError ? err.message : t('common.deleteFailed'),
      )
    }
  }

  async function moveStep(index: number, direction: -1 | 1) {
    const target = index + direction
    if (target < 0 || target >= steps.length) return
    const ids = steps.map((s) => s.id)
    const tmp = ids[index]!
    ids[index] = ids[target]!
    ids[target] = tmp
    setActionError(null)
    try {
      await reorder.mutateAsync(ids)
    } catch (err) {
      setActionError(
        err instanceof ApiError ? err.message : t('programs.steps.reorderFailed'),
      )
    }
  }

  if (isLoading) return <LoadingBlock label={t('programs.steps.loading')} />
  if (error) {
    return <ErrorAlert message={(error as Error).message} />
  }

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <div>
          <h2 className="text-lg font-semibold">{t('programs.steps.title')}</h2>
          <p className="text-sm text-[var(--color-muted)]">
            {t('programs.steps.countHint', { count: steps.length })}
          </p>
        </div>
        {!readOnly ? (
          <Button
            variant="secondary"
            onClick={() => {
              setEditing(null)
              setShowCreate(true)
            }}
          >
            {t('programs.steps.add')}
          </Button>
        ) : null}
      </div>

      {actionError ? <ErrorAlert message={actionError} /> : null}

      {showCreate && !readOnly ? (
        <div className="rounded-lg border border-[var(--color-border)] bg-white p-4">
          <h3 className="mb-3 text-sm font-semibold">{t('programs.steps.new')}</h3>
          <StepForm
            initial={emptyForm}
            submitLabel={t('programs.steps.create')}
            pending={create.isPending}
            onSubmit={onCreate}
            onCancel={() => setShowCreate(false)}
          />
        </div>
      ) : null}

      {editing && !readOnly ? (
        <div className="rounded-lg border border-[var(--color-border)] bg-white p-4">
          <h3 className="mb-3 text-sm font-semibold">{t('programs.steps.edit')}</h3>
          <StepForm
            key={editing.id}
            initial={{
              title: editing.title,
              description: editing.description ?? '',
              step_type: editing.step_type as StepType,
              content_body: stepContentBody(editing.content),
              content_url: stepContentUrl(editing.content),
              content_questions: stepContentQuestions(editing.content),
              is_required: editing.is_required,
              estimated_minutes:
                editing.estimated_minutes != null
                  ? String(editing.estimated_minutes)
                  : '',
            }}
            submitLabel={t('programs.steps.save')}
            pending={update.isPending}
            onSubmit={onUpdate}
            onCancel={() => setEditing(null)}
          />
        </div>
      ) : null}

      {steps.length === 0 ? (
        <EmptyState
          title={t('programs.steps.emptyTitle')}
          description={
            readOnly
              ? t('programs.steps.emptyDescription')
              : t('programs.steps.emptyHint')
          }
        />
      ) : (
        <div className="overflow-hidden rounded-lg border border-[var(--color-border)] bg-white">
          <table className="min-w-full text-left text-sm">
            <thead className="bg-slate-50 text-xs uppercase text-[var(--color-muted)]">
              <tr>
                <th className="px-4 py-3">{t('programs.steps.colNumber')}</th>
                <th className="px-4 py-3">{t('programs.steps.colTitle')}</th>
                <th className="px-4 py-3">{t('programs.steps.colType')}</th>
                <th className="px-4 py-3">{t('programs.steps.colRequired')}</th>
                <th className="px-4 py-3">{t('programs.steps.colMinutes')}</th>
                {!readOnly ? <th className="px-4 py-3" /> : null}
              </tr>
            </thead>
            <tbody className="divide-y divide-[var(--color-border)]">
              {steps.map((step, index) => (
                <tr key={step.id}>
                  <td className="px-4 py-3 text-[var(--color-muted)]">
                    {step.position + 1}
                  </td>
                  <td className="px-4 py-3 font-medium">{step.title}</td>
                  <td className="px-4 py-3">
                    <Badge>{labelStepType(step.step_type)}</Badge>
                  </td>
                  <td className="px-4 py-3 text-[var(--color-muted)]">
                    {step.is_required ? t('common.yes') : t('common.no')}
                  </td>
                  <td className="px-4 py-3 text-[var(--color-muted)]">
                    {step.estimated_minutes ?? t('common.emDash')}
                  </td>
                  {!readOnly ? (
                    <td className="px-4 py-3">
                      <div className="flex flex-wrap justify-end gap-2">
                        <Button
                          variant="ghost"
                          disabled={index === 0 || reorder.isPending}
                          onClick={() => void moveStep(index, -1)}
                        >
                          {t('programs.steps.up')}
                        </Button>
                        <Button
                          variant="ghost"
                          disabled={
                            index === steps.length - 1 || reorder.isPending
                          }
                          onClick={() => void moveStep(index, 1)}
                        >
                          {t('programs.steps.down')}
                        </Button>
                        <Button
                          variant="secondary"
                          onClick={() => {
                            setShowCreate(false)
                            setEditing(step)
                          }}
                        >
                          {t('common.edit')}
                        </Button>
                        <Button
                          variant="danger"
                          disabled={remove.isPending}
                          onClick={() => void onDelete(step)}
                        >
                          {t('common.delete')}
                        </Button>
                      </div>
                    </td>
                  ) : null}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}

import { useState, type FormEvent } from 'react'
import { labelStepType, t } from '../../i18n'
import { Button } from '../ui/Button'
import { Input, Label, Select, Textarea } from '../ui/Field'
import { STEP_TYPES, type StepType } from '../../types/step'
import {
  newContentBlock,
  type ContentBlockDraft,
  type StepFormValues,
} from './stepFormUtils'

interface StepFormProps {
  initial: StepFormValues
  submitLabel: string
  pending?: boolean
  onSubmit: (values: StepFormValues) => Promise<void>
  onCancel?: () => void
}

function validate(values: StepFormValues): string | null {
  const title = values.title.trim()
  if (!title) return t('programs.steps.validation.titleRequired')
  if (title.length > 255) return t('programs.steps.validation.titleMax')
  if (values.description.length > 5000) {
    return t('programs.steps.validation.descriptionMax')
  }
  if (!STEP_TYPES.includes(values.step_type)) {
    return t('programs.steps.validation.typeInvalid')
  }
  const minutes = values.estimated_minutes.trim()
  if (minutes) {
    if (!/^\d+$/.test(minutes)) {
      return t('programs.steps.validation.minutesInvalid')
    }
  }
  if (values.step_type === 'quiz' && !values.content_questions.trim()) {
    return t('programs.steps.validation.questionsRequired')
  }
  return null
}

function moveBlock(
  blocks: ContentBlockDraft[],
  index: number,
  direction: -1 | 1,
): ContentBlockDraft[] {
  const target = index + direction
  if (target < 0 || target >= blocks.length) return blocks
  const next = [...blocks]
  const current = next[index]!
  next[index] = next[target]!
  next[target] = current
  return next
}

export function StepForm({
  initial,
  submitLabel,
  pending,
  onSubmit,
  onCancel,
}: StepFormProps) {
  const [values, setValues] = useState(initial)
  const [error, setError] = useState<string | null>(null)

  async function handleSubmit(e: FormEvent) {
    e.preventDefault()
    const validationError = validate(values)
    if (validationError) {
      setError(validationError)
      return
    }
    setError(null)
    try {
      await onSubmit({
        ...values,
        title: values.title.trim(),
        description: values.description.trim(),
        content_body: values.content_body,
        estimated_minutes: values.estimated_minutes.trim(),
      })
    } catch (err) {
      setError(err instanceof Error ? err.message : t('common.saveFailed'))
    }
  }

  function updateBlock(index: number, text: string) {
    const next = values.content_blocks.map((block, i) =>
      i === index ? { ...block, text } : block,
    )
    setValues({ ...values, content_blocks: next })
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-3" noValidate>
      {error ? (
        <div className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-800">
          {error}
        </div>
      ) : null}

      <div>
        <Label htmlFor="step-title">{t('common.name')}</Label>
        <Input
          id="step-title"
          value={values.title}
          onChange={(e) => setValues({ ...values, title: e.target.value })}
          required
          maxLength={255}
        />
      </div>

      <div>
        <Label htmlFor="step-description">{t('common.description')}</Label>
        <Textarea
          id="step-description"
          rows={3}
          value={values.description}
          onChange={(e) =>
            setValues({ ...values, description: e.target.value })
          }
          placeholder={t('common.optional')}
        />
      </div>

      <div className="grid gap-3 md:grid-cols-2">
        <div>
          <Label htmlFor="step-type">{t('programs.steps.colType')}</Label>
          <Select
            id="step-type"
            value={values.step_type}
            onChange={(e) =>
              setValues({
                ...values,
                step_type: e.target.value as StepType,
              })
            }
          >
            {STEP_TYPES.map((stepType) => (
              <option key={stepType} value={stepType}>
                {labelStepType(stepType)}
              </option>
            ))}
          </Select>
        </div>
        <div>
          <Label htmlFor="step-minutes">{t('programs.steps.estimatedMinutes')}</Label>
          <Input
            id="step-minutes"
            inputMode="numeric"
            value={values.estimated_minutes}
            onChange={(e) =>
              setValues({ ...values, estimated_minutes: e.target.value })
            }
            placeholder={t('common.optional')}
          />
        </div>
      </div>

      {values.step_type === 'content' ? (
        <div className="space-y-2">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <Label>{t('programs.steps.contentBlocks')}</Label>
            <Button
              type="button"
              variant="secondary"
              onClick={() =>
                setValues({
                  ...values,
                  content_blocks: [
                    ...values.content_blocks,
                    newContentBlock('', values.content_blocks.length),
                  ],
                })
              }
            >
              {t('programs.steps.addBlock')}
            </Button>
          </div>
          {values.content_blocks.length === 0 ? (
            <p className="text-xs text-[var(--color-muted)]">
              {t('programs.steps.blocksEmpty')}
            </p>
          ) : (
            <ol className="space-y-3">
              {values.content_blocks.map((block, index) => (
                <li
                  key={block.id}
                  className="rounded-md border border-[var(--color-border)] p-3"
                >
                  <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
                    <span className="text-xs font-medium text-[var(--color-muted)]">
                      {t('programs.steps.blockLabel', { n: index + 1 })}
                    </span>
                    <div className="flex flex-wrap gap-1">
                      <Button
                        type="button"
                        variant="ghost"
                        disabled={index === 0}
                        onClick={() =>
                          setValues({
                            ...values,
                            content_blocks: moveBlock(
                              values.content_blocks,
                              index,
                              -1,
                            ),
                          })
                        }
                      >
                        {t('programs.steps.up')}
                      </Button>
                      <Button
                        type="button"
                        variant="ghost"
                        disabled={index === values.content_blocks.length - 1}
                        onClick={() =>
                          setValues({
                            ...values,
                            content_blocks: moveBlock(
                              values.content_blocks,
                              index,
                              1,
                            ),
                          })
                        }
                      >
                        {t('programs.steps.down')}
                      </Button>
                      <Button
                        type="button"
                        variant="danger"
                        onClick={() =>
                          setValues({
                            ...values,
                            content_blocks: values.content_blocks.filter(
                              (_, i) => i !== index,
                            ),
                          })
                        }
                      >
                        {t('common.delete')}
                      </Button>
                    </div>
                  </div>
                  <Textarea
                    id={`step-block-${block.id}`}
                    rows={3}
                    value={block.text}
                    onChange={(e) => updateBlock(index, e.target.value)}
                    placeholder={t('programs.steps.contentPlaceholder')}
                  />
                </li>
              ))}
            </ol>
          )}
        </div>
      ) : (
        <div>
          <Label htmlFor="step-content">{t('programs.steps.contentBody')}</Label>
          <Textarea
            id="step-content"
            rows={4}
            value={values.content_body}
            onChange={(e) =>
              setValues({ ...values, content_body: e.target.value })
            }
            placeholder={t('programs.steps.contentPlaceholder')}
          />
        </div>
      )}

      {values.step_type === 'task' ? (
        <div>
          <Label htmlFor="step-url">{t('programs.steps.taskUrl')}</Label>
          <Input
            id="step-url"
            type="url"
            value={values.content_url}
            onChange={(e) =>
              setValues({ ...values, content_url: e.target.value })
            }
            placeholder={t('programs.steps.taskUrlPlaceholder')}
          />
        </div>
      ) : null}

      {values.step_type === 'quiz' ? (
        <div>
          <Label htmlFor="step-questions">{t('programs.steps.questions')}</Label>
          <Textarea
            id="step-questions"
            rows={5}
            value={values.content_questions}
            onChange={(e) =>
              setValues({ ...values, content_questions: e.target.value })
            }
            placeholder={t('programs.steps.questionsPlaceholder')}
            required
          />
          <p className="mt-1 text-xs text-[var(--color-muted)]">
            {t('programs.steps.questionsHint')}
          </p>
        </div>
      ) : null}

      {values.step_type === 'ack' ? (
        <p className="text-xs text-[var(--color-muted)]">
          {t('programs.steps.ackHint')}
        </p>
      ) : null}

      <label className="flex items-center gap-2 text-sm">
        <input
          type="checkbox"
          checked={values.is_required}
          onChange={(e) =>
            setValues({ ...values, is_required: e.target.checked })
          }
        />
        {t('programs.steps.requiredStep')}
      </label>

      <div className="flex flex-wrap gap-2">
        <Button type="submit" disabled={pending}>
          {pending ? t('common.saving') : submitLabel}
        </Button>
        {onCancel ? (
          <Button type="button" variant="secondary" onClick={onCancel}>
            {t('common.cancel')}
          </Button>
        ) : null}
      </div>
    </form>
  )
}

import { useState, type FormEvent } from 'react'
import { labelStepType, t } from '../../i18n'
import { Button } from '../ui/Button'
import { Input, Label, Select, Textarea } from '../ui/Field'
import { STEP_TYPES, type StepType } from '../../types/step'
import type { StepFormValues } from './stepFormUtils'

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

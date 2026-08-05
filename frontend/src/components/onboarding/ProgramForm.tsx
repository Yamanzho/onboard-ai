import { useState, type FormEvent } from 'react'
import { t } from '../../i18n'
import { Button } from '../ui/Button'
import { Input, Label, Textarea } from '../ui/Field'

export interface ProgramFormValues {
  title: string
  description: string
}

interface ProgramFormProps {
  initial: ProgramFormValues
  submitLabel: string
  pending?: boolean
  onSubmit: (values: ProgramFormValues) => Promise<void>
}

function validate(values: ProgramFormValues): string | null {
  const title = values.title.trim()
  if (!title) return t('programs.validation.titleRequired')
  if (title.length > 255) return t('programs.validation.titleMax')
  if (values.description.length > 5000) {
    return t('programs.validation.descriptionMax')
  }
  return null
}

export function ProgramForm({
  initial,
  submitLabel,
  pending,
  onSubmit,
}: ProgramFormProps) {
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
        title: values.title.trim(),
        description: values.description.trim(),
      })
    } catch (err) {
      setError(err instanceof Error ? err.message : t('common.saveFailed'))
    }
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-4" noValidate>
      {error ? (
        <div className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-800">
          {error}
        </div>
      ) : null}

      <div>
        <Label htmlFor="program-title">{t('common.name')}</Label>
        <Input
          id="program-title"
          value={values.title}
          onChange={(e) => setValues({ ...values, title: e.target.value })}
          required
          maxLength={255}
        />
      </div>

      <div>
        <Label htmlFor="program-description">{t('common.description')}</Label>
        <Textarea
          id="program-description"
          rows={5}
          value={values.description}
          onChange={(e) =>
            setValues({ ...values, description: e.target.value })
          }
          maxLength={5000}
          placeholder={t('common.optional')}
        />
      </div>

      <Button type="submit" disabled={pending}>
        {pending ? t('common.saving') : submitLabel}
      </Button>
    </form>
  )
}

import { useState, type FormEvent } from 'react'
import { Button } from '../ui/Button'
import { Input, Label, Select } from '../ui/Field'
import {
  labelEmployeeRole,
  labelEmployeeStatus,
  t,
} from '../../i18n'
import {
  EMPLOYEE_ROLES,
  EMPLOYEE_STATUSES,
  type EmployeeRole,
  type EmployeeStatus,
} from '../../types/employee'

export interface EmployeeFormValues {
  full_name: string
  email: string
  telegram_user_id: string
  role: EmployeeRole
  status: EmployeeStatus
}

interface EmployeeFormProps {
  initial: EmployeeFormValues
  submitLabel: string
  pending?: boolean
  /** When false, role select is hidden (backend remains authoritative). */
  roleEditable?: boolean
  /** When false, status select is read-only. */
  statusEditable?: boolean
  /** When roleEditable, limit selectable roles (defaults to all EMPLOYEE_ROLES). */
  allowedRoles?: EmployeeRole[]
  onSubmit: (values: EmployeeFormValues) => Promise<void>
}

function validate(values: EmployeeFormValues, allowedRoles: EmployeeRole[]): string | null {
  const name = values.full_name.trim()
  if (!name) return t('employees.validation.fullNameRequired')
  if (name.length > 255) return t('employees.validation.fullNameMax')

  const email = values.email.trim()
  if (values.status === 'invited' && !email) {
    return t('employees.validation.emailRequired')
  }
  if (email) {
    if (email.length > 320) return t('employees.validation.emailMax')
    if (!/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)) {
      return t('employees.validation.emailInvalid')
    }
  }

  const telegramRaw = values.telegram_user_id.trim()
  if (telegramRaw) {
    if (!/^\d+$/.test(telegramRaw)) {
      return t('employees.validation.telegramPositive')
    }
    const telegramId = Number(telegramRaw)
    if (!Number.isSafeInteger(telegramId) || telegramId <= 0) {
      return t('employees.validation.telegramPositive')
    }
  }

  if (!allowedRoles.includes(values.role)) {
    return t('employees.validation.roleInvalid')
  }
  if (!EMPLOYEE_STATUSES.includes(values.status)) {
    return t('employees.validation.statusInvalid')
  }

  return null
}

export function EmployeeForm({
  initial,
  submitLabel,
  pending,
  roleEditable = true,
  statusEditable = true,
  allowedRoles: allowedRolesProp,
  onSubmit,
}: EmployeeFormProps) {
  const [values, setValues] = useState(initial)
  const [error, setError] = useState<string | null>(null)
  const roleOptions = allowedRolesProp ?? EMPLOYEE_ROLES

  async function handleSubmit(e: FormEvent) {
    e.preventDefault()
    const validationError = validate(values, roleOptions)
    if (validationError) {
      setError(validationError)
      return
    }
    setError(null)
    try {
      await onSubmit({
        ...values,
        full_name: values.full_name.trim(),
        email: values.email.trim(),
        telegram_user_id: values.telegram_user_id.trim(),
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
        <Label htmlFor="full_name">{t('employees.fullName')}</Label>
        <Input
          id="full_name"
          value={values.full_name}
          onChange={(e) => setValues({ ...values, full_name: e.target.value })}
          required
          maxLength={255}
          autoComplete="name"
        />
      </div>

      <div>
        <Label htmlFor="email">{t('common.email')}</Label>
        <Input
          id="email"
          type="email"
          value={values.email}
          onChange={(e) => setValues({ ...values, email: e.target.value })}
          maxLength={320}
          autoComplete="email"
          required={values.status === 'invited'}
        />
      </div>

      <div>
        <Label htmlFor="telegram_user_id">{t('employees.telegramUserId')}</Label>
        <Input
          id="telegram_user_id"
          inputMode="numeric"
          pattern="[0-9]*"
          value={values.telegram_user_id}
          onChange={(e) =>
            setValues({ ...values, telegram_user_id: e.target.value })
          }
          placeholder={t('employees.telegramOptionalHint')}
        />
      </div>

      <div className={`grid gap-4 ${roleEditable ? 'md:grid-cols-2' : ''}`}>
        {roleEditable ? (
          <div>
            <Label htmlFor="role">{t('common.role')}</Label>
            <Select
              id="role"
              value={values.role}
              onChange={(e) =>
                setValues({ ...values, role: e.target.value as EmployeeRole })
              }
            >
              {roleOptions.map((role) => (
                <option key={role} value={role}>
                  {labelEmployeeRole(role)}
                </option>
              ))}
            </Select>
          </div>
        ) : null}
        <div>
          <Label htmlFor="status">{t('common.status')}</Label>
          <Select
            id="status"
            value={values.status}
            disabled={!statusEditable}
            onChange={(e) =>
              setValues({
                ...values,
                status: e.target.value as EmployeeStatus,
              })
            }
          >
            {EMPLOYEE_STATUSES.map((status) => (
              <option key={status} value={status}>
                {labelEmployeeStatus(status)}
              </option>
            ))}
          </Select>
        </div>
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <Button type="submit" disabled={pending}>
          {pending ? t('common.saving') : submitLabel}
        </Button>
      </div>
    </form>
  )
}

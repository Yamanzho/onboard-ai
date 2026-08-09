import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { ErrorAlert, PageHeader } from '../../components/common/PageHeader'
import {
  EmployeeForm,
  type EmployeeFormValues,
} from '../../components/employees/EmployeeForm'
import { useEmployeeMutations } from '../../hooks/useEmployees'
import { t } from '../../i18n'
import { ApiError } from '../../services/apiClient'
import type { Employee } from '../../types/employee'

export function EmployeeCreatePage() {
  const navigate = useNavigate()
  const { create } = useEmployeeMutations()
  const [inviteNotice, setInviteNotice] = useState<string | null>(null)

  async function onSubmit(values: EmployeeFormValues) {
    try {
      const created: Employee = await create.mutateAsync({
        full_name: values.full_name,
        email: values.email || null,
        telegram_user_id: Number(values.telegram_user_id),
        role: values.role,
        status: values.status,
      })
      if (created.invite_delivery === 'manual_url' && created.invite_url) {
        setInviteNotice(
          t('employees.inviteManualUrl', { url: created.invite_url }),
        )
        return
      }
      if (created.invite_email_sent) {
        navigate('/employees')
        return
      }
      navigate('/employees')
    } catch (err) {
      throw new Error(
        err instanceof ApiError ? err.message : t('employees.createFailed'),
      )
    }
  }

  return (
    <div>
      <PageHeader
        title={t('employees.createTitle')}
        description={t('employees.createDescription')}
      />
      {create.isError ? (
        <ErrorAlert
          message={
            create.error instanceof Error
              ? create.error.message
              : t('common.createFailed')
          }
        />
      ) : null}
      {inviteNotice ? (
        <div className="mb-4 rounded-lg border border-[var(--color-border)] bg-white p-4 text-sm">
          <p>{inviteNotice}</p>
          <button
            type="button"
            className="mt-3 text-[var(--color-accent)]"
            onClick={() => navigate('/employees')}
          >
            {t('common.back')}
          </button>
        </div>
      ) : (
        <div className="rounded-lg border border-[var(--color-border)] bg-white p-5">
          <EmployeeForm
            initial={{
              full_name: '',
              email: '',
              telegram_user_id: '',
              role: 'employee',
              status: 'invited',
            }}
            submitLabel={t('employees.create')}
            pending={create.isPending}
            onSubmit={onSubmit}
          />
        </div>
      )}
    </div>
  )
}

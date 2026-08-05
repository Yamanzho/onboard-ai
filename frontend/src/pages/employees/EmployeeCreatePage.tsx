import { useNavigate } from 'react-router-dom'
import { ErrorAlert, PageHeader } from '../../components/common/PageHeader'
import {
  EmployeeForm,
  type EmployeeFormValues,
} from '../../components/employees/EmployeeForm'
import { useEmployeeMutations } from '../../hooks/useEmployees'
import { t } from '../../i18n'
import { ApiError } from '../../services/apiClient'

export function EmployeeCreatePage() {
  const navigate = useNavigate()
  const { create } = useEmployeeMutations()

  async function onSubmit(values: EmployeeFormValues) {
    try {
      await create.mutateAsync({
        full_name: values.full_name,
        email: values.email || null,
        telegram_user_id: Number(values.telegram_user_id),
        role: values.role,
        status: values.status,
      })
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
    </div>
  )
}

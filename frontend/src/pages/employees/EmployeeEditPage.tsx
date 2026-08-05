import { Link, useNavigate, useParams } from 'react-router-dom'
import {
  ErrorAlert,
  LoadingBlock,
  PageHeader,
} from '../../components/common/PageHeader'
import {
  EmployeeForm,
  type EmployeeFormValues,
} from '../../components/employees/EmployeeForm'
import {
  EmployeeRoleBadge,
  EmployeeStatusBadge,
} from '../../components/employees/EmployeeBadges'
import { Button } from '../../components/ui/Button'
import { useEmployee, useEmployeeMutations } from '../../hooks/useEmployees'
import { t } from '../../i18n'
import { ApiError } from '../../services/apiClient'
import type { EmployeeRole, EmployeeStatus } from '../../types/employee'

export function EmployeeEditPage() {
  const { employeeId } = useParams<{ employeeId: string }>()
  const navigate = useNavigate()
  const { data: employee, isLoading, error } = useEmployee(employeeId)
  const { update } = useEmployeeMutations()

  async function onSubmit(values: EmployeeFormValues) {
    if (!employeeId) return
    try {
      await update.mutateAsync({
        id: employeeId,
        payload: {
          full_name: values.full_name,
          email: values.email || null,
          telegram_user_id: Number(values.telegram_user_id),
          role: values.role,
          status: values.status,
        },
      })
      navigate(`/employees/${employeeId}`)
    } catch (err) {
      throw new Error(
        err instanceof ApiError ? err.message : t('employees.updateFailed'),
      )
    }
  }

  if (isLoading) return <LoadingBlock />
  if (error || !employee) {
    return (
      <ErrorAlert
        message={
          error instanceof Error ? error.message : t('employees.notFound')
        }
      />
    )
  }

  return (
    <div>
      <PageHeader
        title={t('employees.editTitle', { name: employee.full_name })}
        description={t('employees.editDescription')}
        action={
          <Link to={`/employees/${employee.id}`}>
            <Button variant="secondary">{t('employees.backToDetails')}</Button>
          </Link>
        }
      />

      <div className="mb-4 flex flex-wrap items-center gap-3 rounded-lg border border-[var(--color-border)] bg-white px-4 py-3 text-sm">
        <EmployeeRoleBadge role={employee.role} />
        <EmployeeStatusBadge status={employee.status} />
        <span className="text-[var(--color-muted)]">
          {t('common.id')}: {employee.id}
        </span>
      </div>

      <div className="rounded-lg border border-[var(--color-border)] bg-white p-5">
        <EmployeeForm
          key={employee.id}
          initial={{
            full_name: employee.full_name,
            email: employee.email ?? '',
            telegram_user_id: String(employee.telegram_user_id),
            role: employee.role as EmployeeRole,
            status: employee.status as EmployeeStatus,
          }}
          submitLabel={t('employees.saveChanges')}
          pending={update.isPending}
          onSubmit={onSubmit}
        />
      </div>
    </div>
  )
}

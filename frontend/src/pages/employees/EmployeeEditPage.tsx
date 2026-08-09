import { Link, useLocation, useNavigate, useParams } from 'react-router-dom'
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
import { useAuth } from '../../hooks/useAuth'
import { useEmployee, useEmployeeMutations } from '../../hooks/useEmployees'
import { useWorkspacePaths } from '../../hooks/useWorkspacePaths'
import { t } from '../../i18n'
import { ApiError } from '../../services/apiClient'
import type { EmployeeRole, EmployeeStatus, EmployeeUpdate } from '../../types/employee'

export function EmployeeEditPage() {
  const { employeeId } = useParams<{ employeeId: string }>()
  const navigate = useNavigate()
  const { pathname } = useLocation()
  const paths = useWorkspacePaths()
  const { user } = useAuth()
  const { data: employee, isLoading, error } = useEmployee(employeeId)
  const { update } = useEmployeeMutations()
  const isAdmin = user?.role === 'admin'
  const inHrMgmt = /\/hr(\/|$)/.test(pathname) && !pathname.includes('/employees')
  const detailPath = (id: string) =>
    inHrMgmt ? paths.hrDetail(id) : paths.employee(id)

  async function onSubmit(values: EmployeeFormValues) {
    if (!employeeId) return
    try {
      const payload: EmployeeUpdate = {
        full_name: values.full_name,
        email: values.email || null,
      }
      if (values.telegram_user_id) {
        payload.telegram_user_id = Number(values.telegram_user_id)
      }
      if (isAdmin) {
        payload.role = values.role
        payload.status = values.status
      }
      await update.mutateAsync({
        id: employeeId,
        payload,
      })
      navigate(detailPath(employeeId))
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

  const roleOptions: EmployeeRole[] = inHrMgmt
    ? ['hr']
    : isAdmin
      ? ['employee', 'hr']
      : [employee.role as EmployeeRole]

  return (
    <div>
      <PageHeader
        title={t('employees.editTitle', { name: employee.full_name })}
        description={t('employees.editDescription')}
        action={
          <Link to={detailPath(employee.id)}>
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
            telegram_user_id:
              employee.telegram_user_id > 0
                ? String(employee.telegram_user_id)
                : '',
            role: employee.role as EmployeeRole,
            status: employee.status as EmployeeStatus,
          }}
          submitLabel={t('employees.saveChanges')}
          pending={update.isPending}
          roleEditable={isAdmin && !inHrMgmt}
          statusEditable={isAdmin}
          allowedRoles={roleOptions}
          onSubmit={onSubmit}
        />
      </div>
    </div>
  )
}

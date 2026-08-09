import { Link, useNavigate, useParams } from 'react-router-dom'
import { useState } from 'react'
import {
  ErrorAlert,
  LoadingBlock,
  PageHeader,
} from '../../components/common/PageHeader'
import { EmployeeAssignmentsPanel } from '../../components/assignments/EmployeeAssignmentsPanel'
import {
  EmployeeRoleBadge,
  EmployeeStatusBadge,
} from '../../components/employees/EmployeeBadges'
import { Button } from '../../components/ui/Button'
import { useEmployee, useEmployeeMutations } from '../../hooks/useEmployees'
import { t } from '../../i18n'
import { ApiError } from '../../services/apiClient'
import * as employeesApi from '../../services/employeesApi'

function formatDate(value: string | null) {
  if (!value) return t('common.emDash')
  try {
    return new Date(value).toLocaleString()
  } catch {
    return value
  }
}

type Tab = 'profile' | 'assignments'

export function EmployeeDetailPage() {
  const { employeeId } = useParams<{ employeeId: string }>()
  const navigate = useNavigate()
  const { data: employee, isLoading, error, refetch } = useEmployee(employeeId)
  const { remove } = useEmployeeMutations()
  const [actionError, setActionError] = useState<string | null>(null)
  const [actionSuccess, setActionSuccess] = useState<string | null>(null)
  const [tab, setTab] = useState<Tab>('profile')
  const [resetPending, setResetPending] = useState(false)

  async function onArchive() {
    if (!employee) return
    const ok = window.confirm(
      t('employees.deleteConfirm', { name: employee.full_name }),
    )
    if (!ok) return
    setActionError(null)
    setActionSuccess(null)
    try {
      await remove.mutateAsync(employee.id)
      navigate('/employees')
    } catch (err) {
      setActionError(err instanceof ApiError ? err.message : t('common.deleteFailed'))
    }
  }

  async function onResetPassword() {
    if (!employee) return
    const ok = window.confirm(
      t('employees.resetPasswordConfirm', { name: employee.full_name }),
    )
    if (!ok) return
    setActionError(null)
    setActionSuccess(null)
    setResetPending(true)
    try {
      const result = await employeesApi.initiatePasswordReset(employee.id)
      if (result.delivery === 'manual_url' && result.reset_url) {
        setActionSuccess(
          t('employees.resetPasswordManualUrl', { url: result.reset_url }),
        )
      } else {
        setActionSuccess(t('employees.resetPasswordEmailSent'))
      }
      void refetch()
    } catch (err) {
      setActionError(
        err instanceof ApiError ? err.message : t('employees.resetPasswordFailed'),
      )
    } finally {
      setResetPending(false)
    }
  }

  if (isLoading) return <LoadingBlock />
  if (error || !employee || !employeeId) {
    return (
      <ErrorAlert
        message={
          error instanceof Error ? error.message : t('employees.notFound')
        }
      />
    )
  }

  const telegramStatus =
    employee.telegram_username || employee.telegram_chat_id != null
      ? t('settings.telegramConnected')
      : t('settings.telegramNotConnected')

  const rows: { label: string; value: string }[] = [
    { label: t('employees.fullName'), value: employee.full_name },
    { label: t('common.email'), value: employee.email ?? t('common.emDash') },
    {
      label: t('employees.telegramUserId'),
      value: String(employee.telegram_user_id),
    },
    {
      label: t('employees.telegramUsername'),
      value: employee.telegram_username
        ? `@${employee.telegram_username}`
        : t('common.emDash'),
    },
    { label: t('settings.telegram'), value: telegramStatus },
    {
      label: t('employees.telegramChatId'),
      value:
        employee.telegram_chat_id != null
          ? String(employee.telegram_chat_id)
          : t('common.emDash'),
    },
    {
      label: t('employees.hiredAt'),
      value: employee.hired_at ?? t('common.emDash'),
    },
    { label: t('common.created'), value: formatDate(employee.created_at) },
    { label: t('common.updated'), value: formatDate(employee.updated_at) },
    { label: t('settings.employeeId'), value: employee.id },
    { label: t('settings.companyId'), value: employee.company_id },
  ]

  const canReset =
    employee.status === 'active' && Boolean(employee.email)

  return (
    <div>
      <PageHeader
        title={employee.full_name}
        description={t('employees.profileDescription')}
        action={
          <div className="flex flex-wrap gap-2">
            <Link to="/employees">
              <Button variant="secondary">{t('employees.backToList')}</Button>
            </Link>
            <Link to={`/employees/${employee.id}/edit`}>
              <Button>{t('common.edit')}</Button>
            </Link>
            {canReset ? (
              <Button
                variant="secondary"
                onClick={() => void onResetPassword()}
                disabled={resetPending}
              >
                {resetPending ? t('common.saving') : t('employees.resetPassword')}
              </Button>
            ) : null}
            {employee.status !== 'archived' ? (
              <Button
                variant="danger"
                onClick={() => void onArchive()}
                disabled={remove.isPending}
              >
                {remove.isPending ? t('employees.archiving') : t('employees.archive')}
              </Button>
            ) : null}
          </div>
        }
      />

      {actionError ? <ErrorAlert message={actionError} /> : null}
      {actionSuccess ? (
        <div className="mb-4 rounded-md border border-emerald-200 bg-emerald-50 px-3 py-2 text-sm text-emerald-800 break-all">
          {actionSuccess}
        </div>
      ) : null}

      <div className="mb-4 flex flex-wrap items-center gap-3 rounded-lg border border-[var(--color-border)] bg-white px-4 py-3 text-sm">
        <EmployeeRoleBadge role={employee.role} />
        <EmployeeStatusBadge status={employee.status} />
      </div>

      <div className="mb-4 flex gap-2 border-b border-[var(--color-border)]">
        {(
          [
            ['profile', t('employees.tabProfile')],
            ['assignments', t('employees.tabAssignments')],
          ] as const
        ).map(([id, label]) => (
          <button
            key={id}
            type="button"
            onClick={() => setTab(id)}
            className={`border-b-2 px-3 py-2 text-sm font-medium transition ${
              tab === id
                ? 'border-[var(--color-accent)] text-[var(--color-accent)]'
                : 'border-transparent text-[var(--color-muted)] hover:text-[var(--color-text)]'
            }`}
          >
            {label}
          </button>
        ))}
      </div>

      {tab === 'profile' ? (
        <div className="overflow-hidden rounded-lg border border-[var(--color-border)] bg-white">
          <dl className="divide-y divide-[var(--color-border)]">
            {rows.map((row) => (
              <div
                key={row.label}
                className="grid gap-1 px-4 py-3 sm:grid-cols-[12rem_1fr] sm:gap-4"
              >
                <dt className="text-sm text-[var(--color-muted)]">{row.label}</dt>
                <dd className="break-all text-sm font-medium">{row.value}</dd>
              </div>
            ))}
          </dl>
        </div>
      ) : (
        <EmployeeAssignmentsPanel employeeId={employeeId} />
      )}
    </div>
  )
}

import { Link, useLocation, useNavigate, useParams } from 'react-router-dom'
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
import { useWorkspacePaths } from '../../hooks/useWorkspacePaths'
import { t } from '../../i18n'
import { ApiError } from '../../services/apiClient'
import * as employeesApi from '../../services/employeesApi'
import type { Employee } from '../../types/employee'

function formatDate(value: string | null) {
  if (!value) return t('common.emDash')
  try {
    return new Date(value).toLocaleString()
  } catch {
    return value
  }
}

async function copyText(value: string): Promise<void> {
  await navigator.clipboard.writeText(value)
}

type Tab = 'profile' | 'assignments'

export function EmployeeDetailPage() {
  const { employeeId } = useParams<{ employeeId: string }>()
  const navigate = useNavigate()
  const { pathname } = useLocation()
  const paths = useWorkspacePaths()
  const inHrMgmt = /\/hr(\/|$)/.test(pathname) && !pathname.includes('/employees')
  const listPath = inHrMgmt ? paths.hr : paths.employees
  const editPath = (id: string) =>
    inHrMgmt ? paths.path(`/hr/${id}/edit`) : paths.employeeEdit(id)
  const { data: employee, isLoading, error, refetch } = useEmployee(employeeId)
  const { remove } = useEmployeeMutations()
  const [actionError, setActionError] = useState<string | null>(null)
  const [actionSuccess, setActionSuccess] = useState<string | null>(null)
  const [tab, setTab] = useState<Tab>('profile')
  const [resetPending, setResetPending] = useState(false)
  const [invitePending, setInvitePending] = useState(false)
  const [inviteLinks, setInviteLinks] = useState<{
    invite_url?: string | null
    telegram_invite_url?: string | null
    invite_email_sent?: boolean | null
  } | null>(null)
  const [copyHint, setCopyHint] = useState<string | null>(null)

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
      navigate(listPath)
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

  async function onResendInvite() {
    if (!employee) return
    setActionError(null)
    setActionSuccess(null)
    setCopyHint(null)
    setInvitePending(true)
    try {
      const result: Employee = await employeesApi.resendInvite(employee.id)
      setInviteLinks({
        invite_url: result.invite_url,
        telegram_invite_url: result.telegram_invite_url,
        invite_email_sent: result.invite_email_sent,
      })
      if (result.invite_email_sent) {
        setActionSuccess(t('employees.inviteEmailSent'))
      } else {
        setActionSuccess(t('employees.inviteSmtpOff'))
      }
      void refetch()
    } catch (err) {
      setActionError(
        err instanceof ApiError ? err.message : t('employees.resendInviteFailed'),
      )
    } finally {
      setInvitePending(false)
    }
  }

  async function onCopy(label: string, value: string) {
    try {
      await copyText(value)
      setCopyHint(t('employees.inviteCopied', { label }))
    } catch {
      setCopyHint(t('employees.inviteCopyFailed'))
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

  const telegramConnected = Boolean(
    employee.telegram_username || employee.telegram_chat_id != null,
  )
  const telegramStatus = telegramConnected
    ? t('settings.telegramConnected')
    : t('settings.telegramNotConnected')

  const rows: { label: string; value: string }[] = [
    { label: t('employees.fullName'), value: employee.full_name },
    { label: t('common.email'), value: employee.email ?? t('common.emDash') },
    { label: t('common.role'), value: employee.role },
    { label: t('common.status'), value: employee.status },
    { label: t('settings.companyId'), value: employee.company_id },
    { label: t('settings.telegram'), value: telegramStatus },
    {
      label: t('employees.telegramUsername'),
      value: employee.telegram_username
        ? `@${employee.telegram_username}`
        : t('common.emDash'),
    },
    {
      label: t('employees.hiredAt'),
      value: employee.hired_at ?? t('common.emDash'),
    },
    { label: t('common.created'), value: formatDate(employee.created_at) },
    { label: t('common.updated'), value: formatDate(employee.updated_at) },
  ]

  const canReset =
    employee.status === 'active' && Boolean(employee.email)
  const canResendInvite = employee.status === 'invited' && Boolean(employee.email)
  const showTelegramInviteActions =
    !telegramConnected &&
    employee.role === 'employee' &&
    (canResendInvite || Boolean(inviteLinks?.telegram_invite_url))

  return (
    <div>
      <PageHeader
        title={employee.full_name}
        description={t('employees.profileDescription')}
        action={
          <div className="flex flex-wrap gap-2">
            <Link to={listPath}>
              <Button variant="secondary">{t('employees.backToList')}</Button>
            </Link>
            <Link to={editPath(employee.id)}>
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
        <span className="text-[var(--color-muted)]">
          {t('settings.telegram')}: {telegramStatus}
        </span>
      </div>

      {showTelegramInviteActions ? (
        <div className="mb-4 space-y-3 rounded-lg border border-[var(--color-border)] bg-white p-4 text-sm">
          <p className="font-medium">{t('employees.telegramInviteSection')}</p>
          {canResendInvite ? (
            <Button
              type="button"
              variant="secondary"
              disabled={invitePending}
              onClick={() => void onResendInvite()}
            >
              {invitePending
                ? t('common.saving')
                : t('employees.openTelegramInvite')}
            </Button>
          ) : null}
          {inviteLinks?.telegram_invite_url ? (
            <div className="space-y-2">
              <p className="text-[var(--color-muted)]">
                {t('employees.inviteTelegramCreated')}
              </p>
              <code className="block break-all rounded bg-[var(--color-bg)] p-2 text-xs">
                {inviteLinks.telegram_invite_url}
              </code>
              <div className="flex flex-wrap gap-2">
                <Button
                  type="button"
                  onClick={() =>
                    void onCopy(
                      t('employees.inviteTelegramUrl'),
                      inviteLinks.telegram_invite_url!,
                    )
                  }
                >
                  {t('employees.copyTelegramUrl')}
                </Button>
                <a
                  className="inline-flex items-center text-[var(--color-accent)]"
                  href={inviteLinks.telegram_invite_url}
                  target="_blank"
                  rel="noreferrer"
                >
                  {t('employees.openTelegram')}
                </a>
              </div>
            </div>
          ) : null}
          {inviteLinks?.invite_url ? (
            <div className="space-y-2">
              <p className="font-medium">{t('employees.inviteWebUrl')}</p>
              <code className="block break-all rounded bg-[var(--color-bg)] p-2 text-xs">
                {inviteLinks.invite_url}
              </code>
              <Button
                type="button"
                onClick={() =>
                  void onCopy(t('employees.inviteWebUrl'), inviteLinks.invite_url!)
                }
              >
                {t('employees.copyInviteUrl')}
              </Button>
            </div>
          ) : null}
          {copyHint ? <p className="text-[var(--color-muted)]">{copyHint}</p> : null}
        </div>
      ) : null}

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

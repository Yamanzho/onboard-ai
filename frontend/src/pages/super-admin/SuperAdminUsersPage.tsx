import { useMemo, useState } from 'react'
import {
  EmptyState,
  ErrorAlert,
  LoadingBlock,
  PageHeader,
} from '../../components/common/PageHeader'
import {
  EmployeeRoleBadge,
  EmployeeStatusBadge,
} from '../../components/employees/EmployeeBadges'
import { Button } from '../../components/ui/Button'
import { Input, Select } from '../../components/ui/Field'
import {
  usePlatformUserMutations,
  usePlatformUsers,
} from '../../hooks/useSuperAdmin'
import {
  labelEmployeeRole,
  labelEmployeeStatus,
  t,
} from '../../i18n'
import { ApiError } from '../../services/apiClient'
import type { PlatformUser } from '../../types/superAdmin'

const ADMIN_HR_ROLES = ['admin', 'hr'] as const
const ALL_ROLES = ['admin', 'hr', 'employee'] as const
const EMPLOYEE_STATUSES = ['active', 'invited', 'archived'] as const

export function SuperAdminUsersPage() {
  const [search, setSearch] = useState('')
  const [role, setRole] = useState('')
  const [status, setStatus] = useState('')
  const [actionError, setActionError] = useState<string | null>(null)
  const [busyId, setBusyId] = useState<string | null>(null)

  const listParams = useMemo(
    () => ({
      role: role || undefined,
      status: status || undefined,
    }),
    [role, status],
  )

  const { data, isLoading, error } = usePlatformUsers(listParams)
  const { update, block, resendInvite } = usePlatformUserMutations()

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase()
    return (data ?? []).filter((u) => {
      if (!q) return true
      return (
        u.full_name.toLowerCase().includes(q) ||
        (u.email?.toLowerCase().includes(q) ?? false) ||
        (u.company_name?.toLowerCase().includes(q) ?? false) ||
        (u.company_slug?.toLowerCase().includes(q) ?? false)
      )
    })
  }, [data, search])

  async function onRoleChange(user: PlatformUser, nextRole: string) {
    if (nextRole === user.role) return
    setActionError(null)
    setBusyId(user.id)
    try {
      await update.mutateAsync({
        id: user.id,
        payload: { role: nextRole as 'admin' | 'hr' | 'employee' },
      })
    } catch (err) {
      setActionError(err instanceof ApiError ? err.message : t('common.updateFailed'))
    } finally {
      setBusyId(null)
    }
  }

  async function onResend(user: PlatformUser) {
    setActionError(null)
    setBusyId(user.id)
    try {
      await resendInvite.mutateAsync(user.id)
    } catch (err) {
      setActionError(err instanceof ApiError ? err.message : t('superAdmin.users.resendFailed'))
    } finally {
      setBusyId(null)
    }
  }

  async function onBlock(user: PlatformUser) {
    const ok = window.confirm(
      t('superAdmin.users.blockConfirm', { name: user.full_name }),
    )
    if (!ok) return
    setActionError(null)
    setBusyId(user.id)
    try {
      await block.mutateAsync(user.id)
    } catch (err) {
      setActionError(err instanceof ApiError ? err.message : t('common.actionFailed'))
    } finally {
      setBusyId(null)
    }
  }

  return (
    <div>
      <PageHeader
        title={t('superAdmin.users.title')}
        description={t('superAdmin.users.description')}
      />

      {actionError ? <ErrorAlert message={actionError} /> : null}
      {error instanceof Error ? <ErrorAlert message={error.message} /> : null}

      <div className="mb-4 grid gap-3 rounded-lg border border-[var(--color-border)] bg-white p-4 md:grid-cols-3">
        <Input
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder={t('superAdmin.users.searchPlaceholder')}
          aria-label={t('superAdmin.users.searchAria')}
        />
        <Select
          value={role}
          onChange={(e) => setRole(e.target.value)}
          aria-label={t('superAdmin.users.filterRole')}
        >
          <option value="">{t('superAdmin.users.allRolesAdminHr')}</option>
          {ADMIN_HR_ROLES.map((value) => (
            <option key={value} value={value}>
              {labelEmployeeRole(value)}
            </option>
          ))}
        </Select>
        <Select
          value={status}
          onChange={(e) => setStatus(e.target.value)}
          aria-label={t('superAdmin.users.filterStatus')}
        >
          <option value="">{t('common.allStatuses')}</option>
          {EMPLOYEE_STATUSES.map((value) => (
            <option key={value} value={value}>
              {labelEmployeeStatus(value)}
            </option>
          ))}
        </Select>
      </div>

      {isLoading ? (
        <LoadingBlock label={t('superAdmin.users.loading')} />
      ) : filtered.length === 0 ? (
        <EmptyState
          title={t('superAdmin.users.emptyTitle')}
          description={t('superAdmin.users.emptyDescription')}
        />
      ) : (
        <div className="overflow-x-auto rounded-lg border border-[var(--color-border)] bg-white">
          <table className="min-w-full text-left text-sm">
            <thead className="bg-slate-50 text-xs uppercase text-[var(--color-muted)]">
              <tr>
                <th className="px-4 py-3">{t('superAdmin.users.colName')}</th>
                <th className="px-4 py-3">{t('superAdmin.users.colCompany')}</th>
                <th className="px-4 py-3">{t('common.email')}</th>
                <th className="px-4 py-3">{t('common.role')}</th>
                <th className="px-4 py-3">{t('common.status')}</th>
                <th className="px-4 py-3">{t('superAdmin.users.lastLogin')}</th>
                <th className="px-4 py-3" />
              </tr>
            </thead>
            <tbody className="divide-y divide-[var(--color-border)]">
              {filtered.map((user) => (
                <tr key={user.id}>
                  <td className="px-4 py-3 font-medium">{user.full_name}</td>
                  <td className="px-4 py-3 text-[var(--color-muted)]">
                    {user.company_name ?? user.company_id.slice(0, 8)}
                    {user.company_slug ? (
                      <span className="ml-1 text-xs">({user.company_slug})</span>
                    ) : null}
                  </td>
                  <td className="px-4 py-3 text-[var(--color-muted)]">
                    {user.email ?? t('common.emDash')}
                  </td>
                  <td className="px-4 py-3">
                    <div className="flex items-center gap-2">
                      <EmployeeRoleBadge role={user.role} />
                      <Select
                        className="w-28"
                        value={user.role}
                        disabled={busyId === user.id || user.status === 'archived'}
                        onChange={(e) => void onRoleChange(user, e.target.value)}
                        aria-label={t('superAdmin.users.changeRoleFor', {
                          name: user.full_name,
                        })}
                      >
                        {ALL_ROLES.map((value) => (
                          <option key={value} value={value}>
                            {labelEmployeeRole(value)}
                          </option>
                        ))}
                      </Select>
                    </div>
                  </td>
                  <td className="px-4 py-3">
                    <EmployeeStatusBadge status={user.status} />
                  </td>
                  <td className="px-4 py-3 text-[var(--color-muted)]">
                    {user.last_login_at
                      ? new Date(user.last_login_at).toLocaleString()
                      : t('common.emDash')}
                  </td>
                  <td className="px-4 py-3 text-right">
                    <div className="flex justify-end gap-2">
                      {user.status === 'invited' ? (
                        <Button
                          variant="secondary"
                          disabled={busyId === user.id}
                          onClick={() => void onResend(user)}
                        >
                          {t('superAdmin.users.resendInvite')}
                        </Button>
                      ) : null}
                      {user.status !== 'archived' ? (
                        <Button
                          variant="danger"
                          disabled={busyId === user.id}
                          onClick={() => void onBlock(user)}
                        >
                          {t('common.block')}
                        </Button>
                      ) : null}
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}

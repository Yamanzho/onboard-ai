import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
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
  useEmployeeMutations,
  useEmployees,
} from '../../hooks/useEmployees'
import {
  labelEmployeeRole,
  labelEmployeeStatus,
  t,
} from '../../i18n'
import { ApiError } from '../../services/apiClient'
import {
  EMPLOYEE_ROLES,
  EMPLOYEE_STATUSES,
  type Employee,
  type EmployeeStatus,
} from '../../types/employee'

type SortKey = 'full_name' | 'email' | 'role' | 'status' | 'created_at'
type SortDir = 'asc' | 'desc'

const PAGE_SIZE = 10

function matchesSearch(employee: Employee, query: string): boolean {
  if (!query) return true
  const q = query.toLowerCase()
  return (
    employee.full_name.toLowerCase().includes(q) ||
    (employee.email?.toLowerCase().includes(q) ?? false) ||
    (employee.telegram_username?.toLowerCase().includes(q) ?? false) ||
    String(employee.telegram_user_id).includes(q) ||
    employee.id.toLowerCase().includes(q)
  )
}

function compareEmployees(a: Employee, b: Employee, key: SortKey, dir: SortDir) {
  const mul = dir === 'asc' ? 1 : -1
  const av = a[key] ?? ''
  const bv = b[key] ?? ''
  if (typeof av === 'string' && typeof bv === 'string') {
    return av.localeCompare(bv, undefined, { sensitivity: 'base' }) * mul
  }
  return String(av).localeCompare(String(bv)) * mul
}

export function EmployeeListPage() {
  const [search, setSearch] = useState('')
  const [role, setRole] = useState('')
  const [status, setStatus] = useState('')
  const [sortKey, setSortKey] = useState<SortKey>('created_at')
  const [sortDir, setSortDir] = useState<SortDir>('desc')
  const [page, setPage] = useState(1)
  const [actionError, setActionError] = useState<string | null>(null)
  const [deletingId, setDeletingId] = useState<string | null>(null)

  const listFilters = useMemo(
    () => ({
      status: (status || undefined) as EmployeeStatus | undefined,
    }),
    [status],
  )

  const { data, isLoading, error } = useEmployees(listFilters)
  const { remove } = useEmployeeMutations()

  const filtered = useMemo(() => {
    const source = data ?? []
    return source
      .filter((e) => matchesSearch(e, search.trim()))
      .filter((e) => (role ? e.role === role : true))
      .sort((a, b) => compareEmployees(a, b, sortKey, sortDir))
  }, [data, search, role, sortKey, sortDir])

  const totalPages = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE))
  const currentPage = Math.min(page, totalPages)
  const pageItems = filtered.slice(
    (currentPage - 1) * PAGE_SIZE,
    currentPage * PAGE_SIZE,
  )

  function toggleSort(key: SortKey) {
    if (sortKey === key) {
      setSortDir((d) => (d === 'asc' ? 'desc' : 'asc'))
    } else {
      setSortKey(key)
      setSortDir(key === 'created_at' ? 'desc' : 'asc')
    }
  }

  function sortLabel(key: SortKey, label: string) {
    if (sortKey !== key) return label
    return `${label} ${sortDir === 'asc' ? '↑' : '↓'}`
  }

  async function onDelete(employee: Employee) {
    const ok = window.confirm(
      t('employees.deleteConfirm', { name: employee.full_name }),
    )
    if (!ok) return
    setActionError(null)
    setDeletingId(employee.id)
    try {
      await remove.mutateAsync(employee.id)
    } catch (err) {
      setActionError(err instanceof ApiError ? err.message : t('common.deleteFailed'))
    } finally {
      setDeletingId(null)
    }
  }

  return (
    <div>
      <PageHeader
        title={t('employees.title')}
        description={t('employees.description')}
        action={
          <Link to="/employees/new">
            <Button>{t('employees.new')}</Button>
          </Link>
        }
      />

      {actionError ? <ErrorAlert message={actionError} /> : null}
      {error ? <ErrorAlert message={(error as Error).message} /> : null}

      <div className="mb-4 grid gap-3 rounded-lg border border-[var(--color-border)] bg-white p-4 md:grid-cols-3">
        <Input
          value={search}
          onChange={(e) => {
            setSearch(e.target.value)
            setPage(1)
          }}
          placeholder={t('employees.searchPlaceholder')}
          aria-label={t('employees.searchAria')}
        />
        <Select
          value={role}
          onChange={(e) => {
            setRole(e.target.value)
            setPage(1)
          }}
          aria-label={t('employees.filterRole')}
        >
          <option value="">{t('common.allRoles')}</option>
          {EMPLOYEE_ROLES.map((r) => (
            <option key={r} value={r}>
              {labelEmployeeRole(r)}
            </option>
          ))}
        </Select>
        <Select
          value={status}
          onChange={(e) => {
            setStatus(e.target.value)
            setPage(1)
          }}
          aria-label={t('employees.filterStatus')}
        >
          <option value="">{t('common.allStatuses')}</option>
          {EMPLOYEE_STATUSES.map((s) => (
            <option key={s} value={s}>
              {labelEmployeeStatus(s)}
            </option>
          ))}
        </Select>
      </div>

      {isLoading ? (
        <LoadingBlock />
      ) : filtered.length === 0 ? (
        <EmptyState
          title={t('employees.emptyTitle')}
          description={
            (data?.length ?? 0) === 0
              ? t('employees.emptyDescriptionCreate')
              : t('employees.emptyDescriptionFilter')
          }
          actionLabel={(data?.length ?? 0) === 0 ? t('employees.create') : undefined}
          actionTo={(data?.length ?? 0) === 0 ? '/employees/new' : undefined}
        />
      ) : (
        <>
          <div className="overflow-hidden rounded-lg border border-[var(--color-border)] bg-white">
            <table className="min-w-full text-left text-sm">
              <thead className="bg-slate-50 text-xs uppercase text-[var(--color-muted)]">
                <tr>
                  <th className="px-4 py-3">
                    <button
                      type="button"
                      className="font-medium uppercase hover:text-[var(--color-text)]"
                      onClick={() => toggleSort('full_name')}
                    >
                      {sortLabel('full_name', t('employees.colName'))}
                    </button>
                  </th>
                  <th className="px-4 py-3">
                    <button
                      type="button"
                      className="font-medium uppercase hover:text-[var(--color-text)]"
                      onClick={() => toggleSort('email')}
                    >
                      {sortLabel('email', t('employees.colEmail'))}
                    </button>
                  </th>
                  <th className="px-4 py-3">{t('employees.colTelegram')}</th>
                  <th className="px-4 py-3">
                    <button
                      type="button"
                      className="font-medium uppercase hover:text-[var(--color-text)]"
                      onClick={() => toggleSort('role')}
                    >
                      {sortLabel('role', t('common.role'))}
                    </button>
                  </th>
                  <th className="px-4 py-3">
                    <button
                      type="button"
                      className="font-medium uppercase hover:text-[var(--color-text)]"
                      onClick={() => toggleSort('status')}
                    >
                      {sortLabel('status', t('common.status'))}
                    </button>
                  </th>
                  <th className="px-4 py-3" />
                </tr>
              </thead>
              <tbody className="divide-y divide-[var(--color-border)]">
                {pageItems.map((employee) => (
                  <tr key={employee.id}>
                    <td className="px-4 py-3">
                      <Link
                        to={`/employees/${employee.id}`}
                        className="font-medium hover:text-[var(--color-accent)]"
                      >
                        {employee.full_name}
                      </Link>
                    </td>
                    <td className="px-4 py-3 text-[var(--color-muted)]">
                      {employee.email ?? t('common.emDash')}
                    </td>
                    <td className="px-4 py-3 text-[var(--color-muted)]">
                      {employee.telegram_user_id}
                      {employee.telegram_username
                        ? ` · @${employee.telegram_username}`
                        : ''}
                    </td>
                    <td className="px-4 py-3">
                      <EmployeeRoleBadge role={employee.role} />
                    </td>
                    <td className="px-4 py-3">
                      <EmployeeStatusBadge status={employee.status} />
                    </td>
                    <td className="px-4 py-3">
                      <div className="flex justify-end gap-2">
                        <Link to={`/employees/${employee.id}/edit`}>
                          <Button variant="secondary">{t('common.edit')}</Button>
                        </Link>
                        <Button
                          variant="danger"
                          onClick={() => void onDelete(employee)}
                          disabled={deletingId === employee.id || remove.isPending}
                        >
                          {deletingId === employee.id
                            ? t('common.deleting')
                            : t('common.delete')}
                        </Button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <div className="mt-4 flex flex-wrap items-center justify-between gap-3 text-sm text-[var(--color-muted)]">
            <p>
              {t('pagination.showing', {
                start: (currentPage - 1) * PAGE_SIZE + 1,
                end: Math.min(currentPage * PAGE_SIZE, filtered.length),
                total: filtered.length,
              })}
            </p>
            <div className="flex items-center gap-2">
              <Button
                variant="secondary"
                disabled={currentPage <= 1}
                onClick={() => setPage((p) => Math.max(1, p - 1))}
              >
                {t('common.previous')}
              </Button>
              <span>
                {t('pagination.page', {
                  current: currentPage,
                  total: totalPages,
                })}
              </span>
              <Button
                variant="secondary"
                disabled={currentPage >= totalPages}
                onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
              >
                {t('common.next')}
              </Button>
            </div>
          </div>
        </>
      )}
    </div>
  )
}

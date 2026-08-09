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
import { useWorkspacePaths } from '../../hooks/useWorkspacePaths'
import { labelEmployeeStatus, t } from '../../i18n'
import { ApiError } from '../../services/apiClient'
import {
  EMPLOYEE_STATUSES,
  type Employee,
  type EmployeeStatus,
} from '../../types/employee'

type SortKey = 'full_name' | 'email' | 'status' | 'created_at'
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

export function HrListPage() {
  const paths = useWorkspacePaths()
  const [search, setSearch] = useState('')
  const [status, setStatus] = useState('')
  const [sortKey] = useState<SortKey>('created_at')
  const [sortDir] = useState<SortDir>('desc')
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
    const mul = sortDir === 'asc' ? 1 : -1
    return (data ?? [])
      .filter((e) => e.role === 'hr')
      .filter((e) => matchesSearch(e, search.trim()))
      .sort((a, b) => {
        const av = a[sortKey] ?? ''
        const bv = b[sortKey] ?? ''
        return String(av).localeCompare(String(bv), undefined, {
          sensitivity: 'base',
        }) * mul
      })
  }, [data, search, sortKey, sortDir])

  const totalPages = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE))
  const currentPage = Math.min(page, totalPages)
  const pageItems = filtered.slice(
    (currentPage - 1) * PAGE_SIZE,
    currentPage * PAGE_SIZE,
  )

  async function onArchive(employee: Employee) {
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
        title={t('hrManagement.title')}
        description={t('hrManagement.description')}
        action={
          <Link to={paths.hrNew}>
            <Button>{t('hrManagement.new')}</Button>
          </Link>
        }
      />

      {actionError ? <ErrorAlert message={actionError} /> : null}
      {error ? <ErrorAlert message={(error as Error).message} /> : null}

      <div className="mb-4 grid gap-3 rounded-lg border border-[var(--color-border)] bg-white p-4 md:grid-cols-2">
        <Input
          value={search}
          onChange={(e) => {
            setSearch(e.target.value)
            setPage(1)
          }}
          placeholder={t('employees.searchPlaceholder')}
        />
        <Select
          value={status}
          onChange={(e) => {
            setStatus(e.target.value)
            setPage(1)
          }}
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
          title={t('hrManagement.empty')}
          actionLabel={t('hrManagement.new')}
          actionTo={paths.hrNew}
        />
      ) : (
        <>
          <div className="overflow-hidden rounded-lg border border-[var(--color-border)] bg-white">
            <table className="min-w-full text-left text-sm">
              <thead className="bg-slate-50 text-xs uppercase text-[var(--color-muted)]">
                <tr>
                  <th className="px-4 py-3">{t('employees.colName')}</th>
                  <th className="px-4 py-3">{t('employees.colEmail')}</th>
                  <th className="px-4 py-3">{t('common.status')}</th>
                  <th className="px-4 py-3" />
                </tr>
              </thead>
              <tbody className="divide-y divide-[var(--color-border)]">
                {pageItems.map((employee) => (
                  <tr key={employee.id}>
                    <td className="px-4 py-3">
                      <Link
                        to={paths.hrDetail(employee.id)}
                        className="font-medium hover:text-[var(--color-accent)]"
                      >
                        {employee.full_name}
                      </Link>
                    </td>
                    <td className="px-4 py-3 text-[var(--color-muted)]">
                      {employee.email ?? t('common.emDash')}
                    </td>
                    <td className="px-4 py-3">
                      <div className="flex items-center gap-2">
                        <EmployeeRoleBadge role={employee.role} />
                        <EmployeeStatusBadge status={employee.status} />
                      </div>
                    </td>
                    <td className="px-4 py-3">
                      <div className="flex justify-end gap-2">
                        <Link to={`${paths.hrDetail(employee.id)}/edit`}>
                          <Button variant="secondary">{t('common.edit')}</Button>
                        </Link>
                        <Button
                          variant="danger"
                          onClick={() => void onArchive(employee)}
                          disabled={deletingId === employee.id || remove.isPending}
                        >
                          {t('employees.archive')}
                        </Button>
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          <div className="mt-4 text-sm text-[var(--color-muted)]">
            {t('pagination.showing', {
              start: (currentPage - 1) * PAGE_SIZE + 1,
              end: Math.min(currentPage * PAGE_SIZE, filtered.length),
              total: filtered.length,
            })}
          </div>
        </>
      )}
    </div>
  )
}

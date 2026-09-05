import { useMemo, useState } from 'react'
import { useQueries } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import {
  EmptyState,
  ErrorAlert,
  LoadingBlock,
  PageHeader,
} from '../../components/common/PageHeader'
import { AssignmentStatusBadge } from '../../components/assignments/AssignmentStatusBadge'
import { AssignmentPriorityBadge } from '../../components/assignments/AssignmentPriorityBadge'
import { Button } from '../../components/ui/Button'
import { Input, Select } from '../../components/ui/Field'
import {
  useAssignmentMutations,
  useAssignments,
} from '../../hooks/useAssignments'
import { useEmployees } from '../../hooks/useEmployees'
import { usePrograms } from '../../hooks/usePrograms'
import { useCapabilities } from '../../hooks/useCapabilities'
import { useWorkspacePaths } from '../../hooks/useWorkspacePaths'
import { CAPABILITIES } from '../../lib/capabilities'
import { labelAssignmentStatus, labelAssignmentType, t } from '../../i18n'
import { ApiError } from '../../services/apiClient'
import * as assignmentsApi from '../../services/assignmentsApi'
import { assignmentTitle, compareAssignmentsByPriorityDeadline, isAssignmentOverdue } from '../../lib/progressUtils'
import {
  ASSIGNMENT_STATUSES,
  type Assignment,
  type AssignmentStatus,
} from '../../types/assignment'

type SortKey =
  | 'employee'
  | 'program'
  | 'status'
  | 'priority'
  | 'due_at'
  | 'assigned_by'
  | 'created_at'
type SortDir = 'asc' | 'desc'

const PAGE_SIZE = 10

function formatDate(value: string | null | undefined) {
  if (!value) return t('common.emDash')
  try {
    return new Date(value).toLocaleString()
  } catch {
    return value
  }
}

export function AssignmentListPage() {
  const paths = useWorkspacePaths()
  const { can } = useCapabilities()
  const canManage = can(CAPABILITIES.ASSIGNMENTS_MANAGE)
  const [search, setSearch] = useState('')
  const [status, setStatus] = useState('')
  const [sortKey, setSortKey] = useState<SortKey>('priority')
  const [sortDir, setSortDir] = useState<SortDir>('asc')
  const [page, setPage] = useState(1)
  const [actionError, setActionError] = useState<string | null>(null)
  const [busyId, setBusyId] = useState<string | null>(null)

  const listFilters = useMemo(
    () => ({
      status: (status || undefined) as AssignmentStatus | undefined,
    }),
    [status],
  )

  const { data, isLoading, error } = useAssignments(listFilters)
  const { data: employees = [] } = useEmployees()
  const { data: programs = [] } = usePrograms()
  const { cancel } = useAssignmentMutations()

  const employeeName = useMemo(() => {
    const map = new Map(employees.map((e) => [e.id, e.full_name]))
    return (id: string | null) =>
      id ? (map.get(id) ?? id.slice(0, 8)) : t('common.emDash')
  }, [employees])

  const programTitle = useMemo(() => {
    const map = new Map(programs.map((p) => [p.id, p.title]))
    return (id: string | null) =>
      id ? (map.get(id) ?? id.slice(0, 8)) : t('assignments.acknowledgementLabel')
  }, [programs])

  const filteredSorted = useMemo(() => {
    const source = data ?? []
    const q = search.trim().toLowerCase()
    const filtered = source.filter((a) => {
      if (!q) return true
      return (
        employeeName(a.employee_id).toLowerCase().includes(q) ||
        assignmentTitle(a, programTitle).toLowerCase().includes(q) ||
        a.status.toLowerCase().includes(q) ||
        a.id.toLowerCase().includes(q)
      )
    })

    const mul = sortDir === 'asc' ? 1 : -1
    const cmp = (av: string, bv: string) =>
      av.localeCompare(bv, undefined, { sensitivity: 'base' }) * mul

    return [...filtered].sort((a, b) => {
      switch (sortKey) {
        case 'employee':
          return cmp(employeeName(a.employee_id), employeeName(b.employee_id))
        case 'program':
          return cmp(assignmentTitle(a, programTitle), assignmentTitle(b, programTitle))
        case 'status':
          return cmp(a.status, b.status)
        case 'priority': {
          const ranked = compareAssignmentsByPriorityDeadline(a, b)
          return sortDir === 'asc' ? ranked : -ranked
        }
        case 'due_at':
          return cmp(a.due_at ?? '', b.due_at ?? '')
        case 'assigned_by':
          return cmp(
            employeeName(a.assigned_by_id),
            employeeName(b.assigned_by_id),
          )
        case 'created_at':
        default:
          return cmp(a.created_at, b.created_at)
      }
    })
  }, [data, search, sortKey, sortDir, employeeName, programTitle])

  const totalPages = Math.max(1, Math.ceil(filteredSorted.length / PAGE_SIZE))
  const currentPage = Math.min(page, totalPages)
  const pageItems = filteredSorted.slice(
    (currentPage - 1) * PAGE_SIZE,
    currentPage * PAGE_SIZE,
  )

  const progressQueries = useQueries({
    queries: pageItems.map((assignment) => ({
      queryKey: ['assignment-progress', assignment.id],
      queryFn: () => assignmentsApi.getAssignmentProgress(assignment.id),
      enabled: assignment.assignment_type !== 'acknowledgement',
    })),
  })

  function toggleSort(key: SortKey) {
    if (sortKey === key) {
      setSortDir((d) => (d === 'asc' ? 'desc' : 'asc'))
    } else {
      setSortKey(key)
                    setSortDir(key === 'employee' || key === 'program' || key === 'priority' ? 'asc' : 'desc')
    }
  }

  function sortLabel(key: SortKey, label: string) {
    if (sortKey !== key) return label
    return `${label} ${sortDir === 'asc' ? '↑' : '↓'}`
  }

  async function onCancel(assignment: Assignment) {
    const ok = window.confirm(t('assignments.cancelConfirm'))
    if (!ok) return
    setActionError(null)
    setBusyId(assignment.id)
    try {
      await cancel.mutateAsync(assignment.id)
    } catch (err) {
      setActionError(
        err instanceof ApiError ? err.message : t('assignments.cancelFailed'),
      )
    } finally {
      setBusyId(null)
    }
  }

  return (
    <div>
      <PageHeader
        title={t('assignments.title')}
        description={t('assignments.description')}
        action={
          canManage ? (
            <Link to={paths.assignmentNew}>
              <Button>{t('assignments.new')}</Button>
            </Link>
          ) : undefined
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
          placeholder={t('assignments.searchPlaceholder')}
          aria-label={t('assignments.searchAria')}
        />
        <Select
          value={status}
          onChange={(e) => {
            setStatus(e.target.value)
            setPage(1)
          }}
          aria-label={t('assignments.filterStatus')}
        >
          <option value="">{t('common.allStatuses')}</option>
          {ASSIGNMENT_STATUSES.map((s) => (
            <option key={s} value={s}>
              {labelAssignmentStatus(s)}
            </option>
          ))}
        </Select>
      </div>

      {isLoading ? (
        <LoadingBlock />
      ) : filteredSorted.length === 0 ? (
        <EmptyState
          title={t('assignments.emptyTitle')}
          description={
            (data?.length ?? 0) === 0
              ? t('assignments.emptyDescriptionCreate')
              : t('assignments.emptyDescriptionFilter')
          }
          actionLabel={
            (data?.length ?? 0) === 0 && canManage
              ? t('assignments.create')
              : undefined
          }
          actionTo={
            (data?.length ?? 0) === 0 && canManage
              ? paths.assignmentNew
              : undefined
          }
        />
      ) : (
        <>
          <div className="overflow-x-auto rounded-lg border border-[var(--color-border)] bg-white">
            <table className="min-w-full text-left text-sm">
              <thead className="bg-slate-50 text-xs uppercase text-[var(--color-muted)]">
                <tr>
                  {(
                    [
                      ['employee', t('assignments.colEmployee')],
                      ['program', t('assignments.colProgram')],
                    ] as const
                  ).map(([key, label]) => (
                    <th key={key} className="px-4 py-3">
                      <button
                        type="button"
                        className="font-medium uppercase hover:text-[var(--color-text)]"
                        onClick={() => toggleSort(key)}
                      >
                        {sortLabel(key, label)}
                      </button>
                    </th>
                  ))}
                  <th className="px-4 py-3">{t('assignments.assignmentType')}</th>
                  {(
                    [
                      ['status', t('common.status')],
                      ['priority', t('assignments.colPriority')],
                    ] as const
                  ).map(([key, label]) => (
                    <th key={key} className="px-4 py-3">
                      <button
                        type="button"
                        className="font-medium uppercase hover:text-[var(--color-text)]"
                        onClick={() => toggleSort(key)}
                      >
                        {sortLabel(key, label)}
                      </button>
                    </th>
                  ))}
                  <th className="px-4 py-3">{t('assignments.colProgress')}</th>
                  {(
                    [
                      ['due_at', t('assignments.colDueDate')],
                      ['assigned_by', t('assignments.colAssignedBy')],
                      ['created_at', t('assignments.colCreatedAt')],
                    ] as const
                  ).map(([key, label]) => (
                    <th key={key} className="px-4 py-3">
                      <button
                        type="button"
                        className="font-medium uppercase hover:text-[var(--color-text)]"
                        onClick={() => toggleSort(key)}
                      >
                        {sortLabel(key, label)}
                      </button>
                    </th>
                  ))}
                  <th className="px-4 py-3" />
                </tr>
              </thead>
              <tbody className="divide-y divide-[var(--color-border)]">
                {pageItems.map((assignment, index) => {
                  const progress = progressQueries[index]
                  const pct =
                    assignment.assignment_type === 'acknowledgement'
                      ? assignment.acknowledgement?.percentage
                      : progress?.data?.percentage
                  const canCancel =
                    canManage &&
                    (assignment.status === 'pending' ||
                      assignment.status === 'in_progress')
                  const overdue = isAssignmentOverdue(assignment)
                  return (
                    <tr key={assignment.id} className={overdue ? 'bg-red-50/40' : undefined}>
                      <td className="px-4 py-3">
                        <Link
                          to={paths.employee(assignment.employee_id)}
                          className="font-medium hover:text-[var(--color-accent)]"
                        >
                          {employeeName(assignment.employee_id)}
                        </Link>
                      </td>
                      <td className="px-4 py-3">
                        {assignment.program_id ? (
                          <Link
                            to={paths.program(assignment.program_id)}
                            className="hover:text-[var(--color-accent)]"
                          >
                            {assignmentTitle(assignment, programTitle)}
                          </Link>
                        ) : (
                          assignmentTitle(assignment, programTitle)
                        )}
                      </td>
                      <td className="px-4 py-3 text-[var(--color-muted)]">
                        {labelAssignmentType(assignment.assignment_type ?? 'program')}
                      </td>
                      <td className="px-4 py-3">
                        <AssignmentStatusBadge status={assignment.status} />
                      </td>
                      <td className="px-4 py-3">
                        <AssignmentPriorityBadge priority={assignment.priority} />
                      </td>
                      <td className="px-4 py-3 text-[var(--color-muted)]">
                        {progress?.isLoading
                          ? '…'
                          : pct != null
                            ? `${pct}%`
                            : t('common.emDash')}
                      </td>
                      <td className="px-4 py-3 text-[var(--color-muted)]">
                        <span className="flex flex-col">
                          <span>{formatDate(assignment.due_at)}</span>
                          {overdue ? (
                            <span className="text-xs font-medium text-[var(--color-danger)]">
                              {t('assignments.overdue')}
                            </span>
                          ) : null}
                        </span>
                      </td>
                      <td className="px-4 py-3 text-[var(--color-muted)]">
                        {employeeName(assignment.assigned_by_id)}
                      </td>
                      <td className="px-4 py-3 text-[var(--color-muted)]">
                        {formatDate(assignment.created_at)}
                      </td>
                      <td className="px-4 py-3">
                        <div className="flex justify-end gap-2">
                          <Link to={paths.assignment(assignment.id)}>
                            <Button variant="secondary">{t('common.view')}</Button>
                          </Link>
                          {canCancel ? (
                            <Button
                              variant="danger"
                              disabled={
                                busyId === assignment.id || cancel.isPending
                              }
                              onClick={() => void onCancel(assignment)}
                            >
                              {t('common.cancel')}
                            </Button>
                          ) : null}
                        </div>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>

          <div className="mt-4 flex flex-wrap items-center justify-between gap-3 text-sm text-[var(--color-muted)]">
            <p>
              {t('pagination.showing', {
                start: (currentPage - 1) * PAGE_SIZE + 1,
                end: Math.min(currentPage * PAGE_SIZE, filteredSorted.length),
                total: filteredSorted.length,
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

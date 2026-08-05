import { useMemo, useState } from 'react'
import { useQueries } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import {
  EmptyState,
  ErrorAlert,
  LoadingBlock,
  PageHeader,
} from '../components/common/PageHeader'
import { AssignmentStatusBadge } from '../components/assignments/AssignmentStatusBadge'
import { Button } from '../components/ui/Button'
import { Input, Select } from '../components/ui/Field'
import {
  useAssignmentMutations,
  useAssignments,
} from '../hooks/useAssignments'
import { useAuth } from '../hooks/useAuth'
import { useEmployees } from '../hooks/useEmployees'
import { usePrograms } from '../hooks/usePrograms'
import { labelAssignmentStatus, t } from '../i18n'
import {
  averageProgress,
  currentStepTitle,
  isActiveAssignment,
  isAssignmentOverdue,
  lastActivityAt,
} from '../lib/progressUtils'
import { ApiError } from '../services/apiClient'
import * as assignmentsApi from '../services/assignmentsApi'
import * as programsApi from '../services/programsApi'
import {
  ASSIGNMENT_STATUSES,
  type Assignment,
} from '../types/assignment'
import type { Step } from '../types/step'

type SortKey =
  | 'employee'
  | 'program'
  | 'progress'
  | 'status'
  | 'due_at'
  | 'last_activity'
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

export function DashboardPage() {
  const { user } = useAuth()
  const [search, setSearch] = useState('')
  const [status, setStatus] = useState('')
  const [programId, setProgramId] = useState('')
  const [employeeId, setEmployeeId] = useState('')
  const [sortKey, setSortKey] = useState<SortKey>('last_activity')
  const [sortDir, setSortDir] = useState<SortDir>('desc')
  const [page, setPage] = useState(1)
  const [actionError, setActionError] = useState<string | null>(null)
  const [busyId, setBusyId] = useState<string | null>(null)

  const {
    data: employees = [],
    isLoading: employeesLoading,
    error: employeesError,
  } = useEmployees()
  const {
    data: programs = [],
    isLoading: programsLoading,
    error: programsError,
  } = usePrograms()
  const {
    data: assignments = [],
    isLoading: assignmentsLoading,
    error: assignmentsError,
  } = useAssignments()
  const { cancel } = useAssignmentMutations()

  const employeeName = useMemo(() => {
    const map = new Map(employees.map((e) => [e.id, e.full_name]))
    return (id: string) => map.get(id) ?? id.slice(0, 8)
  }, [employees])

  const programTitle = useMemo(() => {
    const map = new Map(programs.map((p) => [p.id, p.title]))
    return (id: string) => map.get(id) ?? id.slice(0, 8)
  }, [programs])

  const progressQueries = useQueries({
    queries: assignments.map((assignment) => ({
      queryKey: ['assignment-progress', assignment.id],
      queryFn: () => assignmentsApi.getAssignmentProgress(assignment.id),
    })),
  })

  const progressByAssignmentId = useMemo(() => {
    const map = new Map<string, (typeof progressQueries)[number]['data']>()
    assignments.forEach((a, i) => {
      map.set(a.id, progressQueries[i]?.data)
    })
    return map
  }, [assignments, progressQueries])

  const programIds = useMemo(
    () => [...new Set(assignments.map((a) => a.program_id))],
    [assignments],
  )

  const stepsQueries = useQueries({
    queries: programIds.map((id) => ({
      queryKey: ['program-steps', id],
      queryFn: () => programsApi.listProgramSteps(id),
    })),
  })

  const stepsByProgramId = useMemo(() => {
    const map = new Map<string, Step[]>()
    programIds.forEach((id, i) => {
      map.set(id, stepsQueries[i]?.data ?? [])
    })
    return map
  }, [programIds, stepsQueries])

  const stats = useMemo(() => {
    const activePrograms = programs.filter((p) => p.is_active).length
    const activeAssignments = assignments.filter(isActiveAssignment).length
    const completed = assignments.filter((a) => a.status === 'completed').length
    const overdue = assignments.filter((a) => isAssignmentOverdue(a)).length
    const avg = averageProgress(
      assignments
        .filter((a) => a.status !== 'cancelled')
        .map((a) => progressByAssignmentId.get(a.id)),
    )
    return {
      employees: employees.length,
      activePrograms,
      activeAssignments,
      completed,
      overdue,
      averageProgress: avg,
    }
  }, [employees, programs, assignments, progressByAssignmentId])

  const filteredSorted = useMemo(() => {
    const q = search.trim().toLowerCase()
    const filtered = assignments.filter((a) => {
      if (status && a.status !== status) return false
      if (programId && a.program_id !== programId) return false
      if (employeeId && a.employee_id !== employeeId) return false
      if (!q) return true
      return (
        employeeName(a.employee_id).toLowerCase().includes(q) ||
        programTitle(a.program_id).toLowerCase().includes(q) ||
        a.status.toLowerCase().includes(q) ||
        a.id.toLowerCase().includes(q)
      )
    })

    const mul = sortDir === 'asc' ? 1 : -1
    const cmpStr = (av: string, bv: string) =>
      av.localeCompare(bv, undefined, { sensitivity: 'base' }) * mul
    const cmpNum = (av: number, bv: number) => (av - bv) * mul

    return [...filtered].sort((a, b) => {
      switch (sortKey) {
        case 'employee':
          return cmpStr(employeeName(a.employee_id), employeeName(b.employee_id))
        case 'program':
          return cmpStr(programTitle(a.program_id), programTitle(b.program_id))
        case 'status':
          return cmpStr(a.status, b.status)
        case 'due_at':
          return cmpStr(a.due_at ?? '', b.due_at ?? '')
        case 'progress': {
          const ap = progressByAssignmentId.get(a.id)?.percentage ?? -1
          const bp = progressByAssignmentId.get(b.id)?.percentage ?? -1
          return cmpNum(ap, bp)
        }
        case 'last_activity': {
          const al =
            lastActivityAt(a, progressByAssignmentId.get(a.id)) ?? a.created_at
          const bl =
            lastActivityAt(b, progressByAssignmentId.get(b.id)) ?? b.created_at
          return cmpStr(al, bl)
        }
        default:
          return 0
      }
    })
  }, [
    assignments,
    search,
    status,
    programId,
    employeeId,
    sortKey,
    sortDir,
    employeeName,
    programTitle,
    progressByAssignmentId,
  ])

  const totalPages = Math.max(1, Math.ceil(filteredSorted.length / PAGE_SIZE))
  const currentPage = Math.min(page, totalPages)
  const pageItems = filteredSorted.slice(
    (currentPage - 1) * PAGE_SIZE,
    currentPage * PAGE_SIZE,
  )

  const loading = employeesLoading || programsLoading || assignmentsLoading
  const errorMessage =
    (employeesError instanceof Error && employeesError.message) ||
    (programsError instanceof Error && programsError.message) ||
    (assignmentsError instanceof Error && assignmentsError.message) ||
    null
  const progressLoading = progressQueries.some((q) => q.isLoading)

  const columnLabels: Record<SortKey, string> = {
    employee: t('dashboard.colEmployee'),
    program: t('dashboard.colProgram'),
    progress: t('dashboard.colProgress'),
    status: t('dashboard.colStatus'),
    due_at: t('dashboard.colDueDate'),
    last_activity: t('dashboard.colLastActivity'),
  }

  function toggleSort(key: SortKey) {
    if (sortKey === key) {
      setSortDir((d) => (d === 'asc' ? 'desc' : 'asc'))
    } else {
      setSortKey(key)
      setSortDir(key === 'employee' || key === 'program' ? 'asc' : 'desc')
    }
  }

  function sortLabel(key: SortKey) {
    const label = columnLabels[key]
    if (sortKey !== key) return label
    return `${label} ${sortDir === 'asc' ? '↑' : '↓'}`
  }

  async function onCancel(assignment: Assignment) {
    const ok = window.confirm(t('dashboard.cancelConfirm'))
    if (!ok) return
    setActionError(null)
    setBusyId(assignment.id)
    try {
      await cancel.mutateAsync(assignment.id)
    } catch (err) {
      setActionError(err instanceof ApiError ? err.message : t('dashboard.cancelFailed'))
    } finally {
      setBusyId(null)
    }
  }

  return (
    <div>
      <PageHeader
        title={t('dashboard.title')}
        description={t('dashboard.description', {
          name: user?.full_name ?? t('dashboard.defaultUser'),
        })}
        action={
          <Link to="/assignments/new">
            <Button>{t('dashboard.newAssignment')}</Button>
          </Link>
        }
      />

      {actionError ? <ErrorAlert message={actionError} /> : null}
      {errorMessage ? <ErrorAlert message={errorMessage} /> : null}

      {loading ? (
        <LoadingBlock label={t('dashboard.loading')} />
      ) : (
        <>
          <div className="mb-6 grid gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-6">
            <StatCard label={t('dashboard.employees')} value={String(stats.employees)} />
            <StatCard
              label={t('dashboard.activePrograms')}
              value={String(stats.activePrograms)}
            />
            <StatCard
              label={t('dashboard.activeAssignments')}
              value={String(stats.activeAssignments)}
            />
            <StatCard label={t('dashboard.completed')} value={String(stats.completed)} />
            <StatCard
              label={t('dashboard.overdue')}
              value={String(stats.overdue)}
              emphasize={stats.overdue > 0}
            />
            <StatCard
              label={t('dashboard.avgProgress')}
              value={progressLoading ? '…' : `${stats.averageProgress}%`}
            />
          </div>

          <div className="mb-4 grid gap-3 rounded-lg border border-[var(--color-border)] bg-white p-4 md:grid-cols-2 xl:grid-cols-4">
            <Input
              value={search}
              onChange={(e) => {
                setSearch(e.target.value)
                setPage(1)
              }}
              placeholder={t('dashboard.searchPlaceholder')}
              aria-label={t('dashboard.searchAria')}
            />
            <Select
              value={programId}
              onChange={(e) => {
                setProgramId(e.target.value)
                setPage(1)
              }}
              aria-label={t('dashboard.filterProgram')}
            >
              <option value="">{t('dashboard.allPrograms')}</option>
              {programs.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.title}
                </option>
              ))}
            </Select>
            <Select
              value={status}
              onChange={(e) => {
                setStatus(e.target.value)
                setPage(1)
              }}
              aria-label={t('dashboard.filterStatus')}
            >
              <option value="">{t('common.allStatuses')}</option>
              {ASSIGNMENT_STATUSES.map((s) => (
                <option key={s} value={s}>
                  {labelAssignmentStatus(s)}
                </option>
              ))}
            </Select>
            <Select
              value={employeeId}
              onChange={(e) => {
                setEmployeeId(e.target.value)
                setPage(1)
              }}
              aria-label={t('dashboard.filterEmployee')}
            >
              <option value="">{t('dashboard.allEmployees')}</option>
              {employees.map((e) => (
                <option key={e.id} value={e.id}>
                  {e.full_name}
                </option>
              ))}
            </Select>
          </div>

          {filteredSorted.length === 0 ? (
            <EmptyState
              title={t('dashboard.emptyTitle')}
              description={
                assignments.length === 0
                  ? t('dashboard.emptyDescriptionCreate')
                  : t('dashboard.emptyDescriptionFilter')
              }
              actionLabel={
                assignments.length === 0 ? t('dashboard.createAssignment') : undefined
              }
              actionTo={assignments.length === 0 ? '/assignments/new' : undefined}
            />
          ) : (
            <>
              <div className="overflow-x-auto rounded-lg border border-[var(--color-border)] bg-white">
                <table className="min-w-full text-left text-sm">
                  <thead className="bg-slate-50 text-xs uppercase text-[var(--color-muted)]">
                    <tr>
                      {(['employee', 'program'] as const).map((key) => (
                        <th key={key} className="px-4 py-3">
                          <button
                            type="button"
                            className="font-medium uppercase hover:text-[var(--color-text)]"
                            onClick={() => toggleSort(key)}
                          >
                            {sortLabel(key)}
                          </button>
                        </th>
                      ))}
                      <th className="px-4 py-3">{t('dashboard.colCurrentStep')}</th>
                      <th className="px-4 py-3">
                        <button
                          type="button"
                          className="font-medium uppercase hover:text-[var(--color-text)]"
                          onClick={() => toggleSort('progress')}
                        >
                          {sortLabel('progress')}
                        </button>
                      </th>
                      <th className="px-4 py-3">
                        <button
                          type="button"
                          className="font-medium uppercase hover:text-[var(--color-text)]"
                          onClick={() => toggleSort('status')}
                        >
                          {sortLabel('status')}
                        </button>
                      </th>
                      <th className="px-4 py-3">
                        <button
                          type="button"
                          className="font-medium uppercase hover:text-[var(--color-text)]"
                          onClick={() => toggleSort('due_at')}
                        >
                          {sortLabel('due_at')}
                        </button>
                      </th>
                      <th className="px-4 py-3">
                        <button
                          type="button"
                          className="font-medium uppercase hover:text-[var(--color-text)]"
                          onClick={() => toggleSort('last_activity')}
                        >
                          {sortLabel('last_activity')}
                        </button>
                      </th>
                      <th className="px-4 py-3" />
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-[var(--color-border)]">
                    {pageItems.map((assignment) => {
                      const progress = progressByAssignmentId.get(assignment.id)
                      const steps = stepsByProgramId.get(assignment.program_id) ?? []
                      const overdue = isAssignmentOverdue(assignment)
                      const canCancel = isActiveAssignment(assignment)
                      return (
                        <tr
                          key={assignment.id}
                          className={overdue ? 'bg-red-50/40' : undefined}
                        >
                          <td className="px-4 py-3">
                            <Link
                              to={`/employees/${assignment.employee_id}`}
                              className="font-medium hover:text-[var(--color-accent)]"
                            >
                              {employeeName(assignment.employee_id)}
                            </Link>
                          </td>
                          <td className="px-4 py-3">
                            <Link
                              to={`/onboarding/${assignment.program_id}`}
                              className="hover:text-[var(--color-accent)]"
                            >
                              {programTitle(assignment.program_id)}
                            </Link>
                          </td>
                          <td className="px-4 py-3 text-[var(--color-muted)]">
                            {currentStepTitle(progress, steps)}
                          </td>
                          <td className="px-4 py-3 text-[var(--color-muted)]">
                            {progress?.percentage != null
                              ? `${progress.percentage}%`
                              : '…'}
                          </td>
                          <td className="px-4 py-3">
                            <div className="flex flex-wrap items-center gap-2">
                              <AssignmentStatusBadge status={assignment.status} />
                              {overdue ? (
                                <span className="text-xs font-medium text-[var(--color-danger)]">
                                  {t('dashboard.overdueLabel')}
                                </span>
                              ) : null}
                            </div>
                          </td>
                          <td className="px-4 py-3 text-[var(--color-muted)]">
                            {formatDate(assignment.due_at)}
                          </td>
                          <td className="px-4 py-3 text-[var(--color-muted)]">
                            {formatDate(
                              lastActivityAt(assignment, progress),
                            )}
                          </td>
                          <td className="px-4 py-3">
                            <div className="flex flex-wrap justify-end gap-2">
                              <Link to={`/assignments/${assignment.id}`}>
                                <Button variant="secondary">{t('dashboard.progress')}</Button>
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
        </>
      )}
    </div>
  )
}

function StatCard({
  label,
  value,
  emphasize,
}: {
  label: string
  value: string
  emphasize?: boolean
}) {
  return (
    <div className="rounded-lg border border-[var(--color-border)] bg-white px-4 py-4">
      <p className="text-xs uppercase tracking-wide text-[var(--color-muted)]">
        {label}
      </p>
      <p
        className={`mt-1 text-2xl font-semibold ${
          emphasize ? 'text-[var(--color-danger)]' : ''
        }`}
      >
        {value}
      </p>
    </div>
  )
}

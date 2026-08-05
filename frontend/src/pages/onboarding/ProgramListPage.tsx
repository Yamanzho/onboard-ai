import { useMemo, useState } from 'react'
import { useQueries } from '@tanstack/react-query'
import { Link } from 'react-router-dom'
import {
  EmptyState,
  ErrorAlert,
  LoadingBlock,
  PageHeader,
} from '../../components/common/PageHeader'
import { ProgramStatusBadge } from '../../components/onboarding/ProgramStatusBadge'
import { Button } from '../../components/ui/Button'
import { Input, Select } from '../../components/ui/Field'
import {
  useProgramMutations,
  usePrograms,
} from '../../hooks/usePrograms'
import { t } from '../../i18n'
import { ApiError } from '../../services/apiClient'
import * as programsApi from '../../services/programsApi'
import type { Program } from '../../types/program'

type SortKey = 'title' | 'created_at' | 'updated_at' | 'status'
type SortDir = 'asc' | 'desc'

const PAGE_SIZE = 10

function matchesSearch(program: Program, query: string): boolean {
  if (!query) return true
  const q = query.toLowerCase()
  return (
    program.title.toLowerCase().includes(q) ||
    (program.description?.toLowerCase().includes(q) ?? false) ||
    program.id.toLowerCase().includes(q)
  )
}

function comparePrograms(a: Program, b: Program, key: SortKey, dir: SortDir) {
  const mul = dir === 'asc' ? 1 : -1
  if (key === 'status') {
    const av = a.is_active ? 1 : 0
    const bv = b.is_active ? 1 : 0
    return (av - bv) * mul
  }
  const av = a[key] ?? ''
  const bv = b[key] ?? ''
  return String(av).localeCompare(String(bv), undefined, { sensitivity: 'base' }) * mul
}

function formatDate(value: string) {
  try {
    return new Date(value).toLocaleString()
  } catch {
    return value
  }
}

export function ProgramListPage() {
  const [search, setSearch] = useState('')
  const [status, setStatus] = useState('')
  const [sortKey, setSortKey] = useState<SortKey>('created_at')
  const [sortDir, setSortDir] = useState<SortDir>('desc')
  const [page, setPage] = useState(1)
  const [actionError, setActionError] = useState<string | null>(null)
  const [busyId, setBusyId] = useState<string | null>(null)

  const listFilters = useMemo(() => {
    if (status === 'published') return { is_active: true as const }
    if (status === 'draft') return { is_active: false as const }
    return {}
  }, [status])

  const { data, isLoading, error } = usePrograms(listFilters)
  const { publish, archive } = useProgramMutations()

  const filtered = useMemo(() => {
    const source = data ?? []
    return source
      .filter((p) => matchesSearch(p, search.trim()))
      .sort((a, b) => comparePrograms(a, b, sortKey, sortDir))
  }, [data, search, sortKey, sortDir])

  const totalPages = Math.max(1, Math.ceil(filtered.length / PAGE_SIZE))
  const currentPage = Math.min(page, totalPages)
  const pageItems = filtered.slice(
    (currentPage - 1) * PAGE_SIZE,
    currentPage * PAGE_SIZE,
  )

  const stepQueries = useQueries({
    queries: pageItems.map((program) => ({
      queryKey: ['program-steps', program.id],
      queryFn: () => programsApi.listProgramSteps(program.id),
    })),
  })

  function toggleSort(key: SortKey) {
    if (sortKey === key) {
      setSortDir((d) => (d === 'asc' ? 'desc' : 'asc'))
    } else {
      setSortKey(key)
      setSortDir(key === 'title' ? 'asc' : 'desc')
    }
  }

  function sortLabel(key: SortKey, label: string) {
    if (sortKey !== key) return label
    return `${label} ${sortDir === 'asc' ? '↑' : '↓'}`
  }

  async function onPublish(program: Program) {
    const ok = window.confirm(
      t('programs.publishConfirm', { title: program.title }),
    )
    if (!ok) return
    setActionError(null)
    setBusyId(program.id)
    try {
      await publish.mutateAsync(program.id)
    } catch (err) {
      setActionError(
        err instanceof ApiError ? err.message : t('programs.publishFailed'),
      )
    } finally {
      setBusyId(null)
    }
  }

  async function onArchive(program: Program) {
    const ok = window.confirm(
      t('programs.archiveConfirm', { title: program.title }),
    )
    if (!ok) return
    setActionError(null)
    setBusyId(program.id)
    try {
      await archive.mutateAsync(program.id)
    } catch (err) {
      setActionError(
        err instanceof ApiError ? err.message : t('programs.archiveFailed'),
      )
    } finally {
      setBusyId(null)
    }
  }

  return (
    <div>
      <PageHeader
        title={t('programs.title')}
        description={t('programs.description')}
        action={
          <Link to="/onboarding/new">
            <Button>{t('programs.new')}</Button>
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
          placeholder={t('programs.searchPlaceholder')}
          aria-label={t('programs.searchAria')}
        />
        <Select
          value={status}
          onChange={(e) => {
            setStatus(e.target.value)
            setPage(1)
          }}
          aria-label={t('programs.filterStatus')}
        >
          <option value="">{t('common.allStatuses')}</option>
          <option value="published">{t('enums.programStatus.published')}</option>
          <option value="draft">{t('enums.programStatus.draft')}</option>
        </Select>
      </div>

      {isLoading ? (
        <LoadingBlock />
      ) : filtered.length === 0 ? (
        <EmptyState
          title={t('programs.emptyTitle')}
          description={
            (data?.length ?? 0) === 0
              ? t('programs.emptyDescriptionCreate')
              : t('programs.emptyDescriptionFilter')
          }
          actionLabel={(data?.length ?? 0) === 0 ? t('programs.create') : undefined}
          actionTo={(data?.length ?? 0) === 0 ? '/onboarding/new' : undefined}
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
                      onClick={() => toggleSort('title')}
                    >
                      {sortLabel('title', t('programs.colTitle'))}
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
                  <th className="px-4 py-3">{t('programs.colSteps')}</th>
                  <th className="px-4 py-3">
                    <button
                      type="button"
                      className="font-medium uppercase hover:text-[var(--color-text)]"
                      onClick={() => toggleSort('created_at')}
                    >
                      {sortLabel('created_at', t('common.created'))}
                    </button>
                  </th>
                  <th className="px-4 py-3" />
                </tr>
              </thead>
              <tbody className="divide-y divide-[var(--color-border)]">
                {pageItems.map((program, index) => {
                  const stepsData = stepQueries[index]?.data
                  const stepsLoading = stepQueries[index]?.isLoading
                  return (
                    <tr key={program.id}>
                      <td className="px-4 py-3">
                        <Link
                          to={`/onboarding/${program.id}`}
                          className="font-medium hover:text-[var(--color-accent)]"
                        >
                          {program.title}
                        </Link>
                        {program.description ? (
                          <p className="mt-0.5 line-clamp-1 text-xs text-[var(--color-muted)]">
                            {program.description}
                          </p>
                        ) : null}
                      </td>
                      <td className="px-4 py-3">
                        <ProgramStatusBadge program={program} />
                      </td>
                      <td className="px-4 py-3 text-[var(--color-muted)]">
                        {stepsLoading
                          ? '…'
                          : (stepsData?.length ?? t('common.emDash'))}
                      </td>
                      <td className="px-4 py-3 text-[var(--color-muted)]">
                        {formatDate(program.created_at)}
                      </td>
                      <td className="px-4 py-3">
                        <div className="flex flex-wrap justify-end gap-2">
                          <Link to={`/onboarding/${program.id}`}>
                            <Button variant="ghost">{t('common.view')}</Button>
                          </Link>
                          <Link to={`/onboarding/${program.id}/edit`}>
                            <Button variant="secondary">{t('common.edit')}</Button>
                          </Link>
                          {!program.is_active ? (
                            <Button
                              variant="secondary"
                              disabled={busyId === program.id || publish.isPending}
                              onClick={() => void onPublish(program)}
                            >
                              {t('common.publish')}
                            </Button>
                          ) : (
                            <Button
                              variant="ghost"
                              disabled={busyId === program.id || archive.isPending}
                              onClick={() => void onArchive(program)}
                            >
                              {t('common.archive')}
                            </Button>
                          )}
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

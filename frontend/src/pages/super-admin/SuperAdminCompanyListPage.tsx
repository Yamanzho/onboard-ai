import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import {
  EmptyState,
  ErrorAlert,
  LoadingBlock,
  PageHeader,
} from '../../components/common/PageHeader'
import { Badge } from '../../components/ui/Badge'
import { Button } from '../../components/ui/Button'
import { Input, Select } from '../../components/ui/Field'
import {
  usePlatformCompanies,
  usePlatformCompanyMutations,
} from '../../hooks/useSuperAdmin'
import { labelCompanyActive, t } from '../../i18n'
import { ApiError } from '../../services/apiClient'
import type { PlatformCompany } from '../../types/superAdmin'

export function SuperAdminCompanyListPage() {
  const [search, setSearch] = useState('')
  const [activeFilter, setActiveFilter] = useState('')
  const [actionError, setActionError] = useState<string | null>(null)
  const [busyId, setBusyId] = useState<string | null>(null)

  const listParams = useMemo(() => {
    if (activeFilter === 'true') return { is_active: true }
    if (activeFilter === 'false') return { is_active: false }
    return undefined
  }, [activeFilter])

  const { data, isLoading, error } = usePlatformCompanies(listParams)
  const { activate, deactivate } = usePlatformCompanyMutations()

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase()
    return (data ?? []).filter((c) => {
      if (!q) return true
      return (
        c.name.toLowerCase().includes(q) ||
        c.slug.toLowerCase().includes(q) ||
        c.id.toLowerCase().includes(q)
      )
    })
  }, [data, search])

  async function toggleActive(company: PlatformCompany) {
    setActionError(null)
    setBusyId(company.id)
    try {
      if (company.is_active) {
        await deactivate.mutateAsync(company.id)
      } else {
        await activate.mutateAsync(company.id)
      }
    } catch (err) {
      setActionError(err instanceof ApiError ? err.message : t('common.actionFailed'))
    } finally {
      setBusyId(null)
    }
  }

  return (
    <div>
      <PageHeader
        title={t('superAdmin.companies.title')}
        description={t('superAdmin.companies.description')}
        action={
          <Link to="/super-admin/companies/new">
            <Button>{t('superAdmin.companies.create')}</Button>
          </Link>
        }
      />

      {actionError ? <ErrorAlert message={actionError} /> : null}
      {error instanceof Error ? <ErrorAlert message={error.message} /> : null}

      <div className="mb-4 grid gap-3 rounded-lg border border-[var(--color-border)] bg-white p-4 md:grid-cols-2">
        <Input
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder={t('superAdmin.companies.searchPlaceholder')}
          aria-label={t('superAdmin.companies.searchAria')}
        />
        <Select
          value={activeFilter}
          onChange={(e) => setActiveFilter(e.target.value)}
          aria-label={t('superAdmin.companies.filterStatus')}
        >
          <option value="">{t('common.allStatuses')}</option>
          <option value="true">{t('superAdmin.companies.active')}</option>
          <option value="false">{t('superAdmin.companies.blocked')}</option>
        </Select>
      </div>

      {isLoading ? (
        <LoadingBlock label={t('superAdmin.companies.loading')} />
      ) : filtered.length === 0 ? (
        <EmptyState
          title={t('superAdmin.companies.emptyTitle')}
          description={t('superAdmin.companies.emptyDescription')}
          actionLabel={t('superAdmin.companies.create')}
          actionTo="/super-admin/companies/new"
        />
      ) : (
        <div className="overflow-x-auto rounded-lg border border-[var(--color-border)] bg-white">
          <table className="min-w-full text-left text-sm">
            <thead className="bg-slate-50 text-xs uppercase text-[var(--color-muted)]">
              <tr>
                <th className="px-4 py-3">{t('superAdmin.companies.colName')}</th>
                <th className="px-4 py-3">{t('superAdmin.companies.colSlug')}</th>
                <th className="px-4 py-3">{t('superAdmin.companies.colTimezone')}</th>
                <th className="px-4 py-3">{t('common.status')}</th>
                <th className="px-4 py-3" />
              </tr>
            </thead>
            <tbody className="divide-y divide-[var(--color-border)]">
              {filtered.map((company) => (
                <tr key={company.id}>
                  <td className="px-4 py-3 font-medium">
                    <Link
                      to={`/super-admin/companies/${company.id}`}
                      className="hover:text-[var(--color-accent)]"
                    >
                      {company.name}
                    </Link>
                  </td>
                  <td className="px-4 py-3 text-[var(--color-muted)]">
                    {company.slug}
                  </td>
                  <td className="px-4 py-3 text-[var(--color-muted)]">
                    {company.timezone}
                  </td>
                  <td className="px-4 py-3">
                    <Badge tone={company.is_active ? 'success' : 'danger'}>
                      {labelCompanyActive(company.is_active)}
                    </Badge>
                  </td>
                  <td className="px-4 py-3">
                    <div className="flex flex-wrap justify-end gap-2">
                      <Link to={`/super-admin/companies/${company.id}`}>
                        <Button variant="secondary">{t('common.view')}</Button>
                      </Link>
                      <Link to={`/super-admin/companies/${company.id}/edit`}>
                        <Button variant="secondary">{t('common.edit')}</Button>
                      </Link>
                      <Button
                        variant={company.is_active ? 'danger' : 'primary'}
                        disabled={busyId === company.id}
                        onClick={() => void toggleActive(company)}
                      >
                        {company.is_active ? t('common.block') : t('common.activate')}
                      </Button>
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

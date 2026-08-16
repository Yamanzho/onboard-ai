import { useMemo, useState } from 'react'
import {
  EmptyState,
  ErrorAlert,
  LoadingBlock,
  PageHeader,
} from '../../components/common/PageHeader'
import { Select } from '../../components/ui/Field'
import { useCompanyAuditLogs } from '../../hooks/useAnalytics'
import { t } from '../../i18n'

const ACTIONS = [
  '',
  'employee.created',
  'employee.updated',
  'employee.archived',
  'invite.created',
  'invite.resent',
  'invite.accepted',
  'program.created',
  'program.published',
  'program.archived',
  'assignment.created',
  'assignment.changed',
  'kb.article.created',
  'kb.article.updated',
  'kb.article.published',
  'kb.article.archived',
] as const

export function CompanyAuditLogPage() {
  const [action, setAction] = useState('')
  const filters = useMemo(
    () => ({ action: action || undefined }),
    [action],
  )
  const { data, isLoading, error, refetch } = useCompanyAuditLogs(filters)
  const items = data?.items ?? []

  return (
    <div>
      <PageHeader
        title={t('companyAudit.title')}
        description={t('companyAudit.description')}
      />
      {error instanceof Error ? (
        <ErrorAlert message={error.message} onRetry={() => void refetch()} />
      ) : null}

      <div className="mb-4 max-w-xs">
        <Select
          value={action}
          onChange={(e) => setAction(e.target.value)}
          aria-label={t('companyAudit.filterAction')}
        >
          <option value="">{t('companyAudit.allActions')}</option>
          {ACTIONS.filter(Boolean).map((value) => (
            <option key={value} value={value}>
              {value}
            </option>
          ))}
        </Select>
      </div>

      {isLoading ? (
        <LoadingBlock label={t('companyAudit.loading')} />
      ) : items.length === 0 ? (
        <EmptyState
          title={t('companyAudit.emptyTitle')}
          description={t('companyAudit.emptyDescription')}
        />
      ) : (
        <div className="overflow-x-auto rounded-lg border border-[var(--color-border)] bg-white">
          <table className="min-w-full text-left text-sm">
            <thead className="bg-slate-50 text-xs uppercase text-[var(--color-muted)]">
              <tr>
                <th className="px-4 py-3">{t('companyAudit.colWhen')}</th>
                <th className="px-4 py-3">{t('companyAudit.colActor')}</th>
                <th className="px-4 py-3">{t('companyAudit.colAction')}</th>
                <th className="px-4 py-3">{t('companyAudit.colResource')}</th>
                <th className="px-4 py-3">{t('companyAudit.colSummary')}</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-[var(--color-border)]">
              {items.map((entry) => (
                <tr key={entry.id}>
                  <td className="px-4 py-3 text-[var(--color-muted)]">
                    {new Date(entry.created_at).toLocaleString()}
                  </td>
                  <td className="px-4 py-3">
                    {entry.actor_name ?? t('common.emDash')}
                  </td>
                  <td className="px-4 py-3 font-mono text-xs">{entry.action}</td>
                  <td className="px-4 py-3">
                    {entry.resource_type}
                    {entry.resource_id ? (
                      <span className="ml-1 text-xs text-[var(--color-muted)]">
                        {entry.resource_id.slice(0, 8)}
                      </span>
                    ) : null}
                  </td>
                  <td className="px-4 py-3">{entry.summary}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}

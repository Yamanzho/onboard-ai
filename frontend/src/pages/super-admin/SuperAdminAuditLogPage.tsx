import {
  EmptyState,
  ErrorAlert,
  LoadingBlock,
  PageHeader,
} from '../../components/common/PageHeader'
import { usePlatformAuditLogs } from '../../hooks/useSuperAdmin'
import { t } from '../../i18n'

export function SuperAdminAuditLogPage() {
  const { data, isLoading, error } = usePlatformAuditLogs()

  return (
    <div>
      <PageHeader
        title={t('superAdmin.audit.title')}
        description={t('superAdmin.audit.description')}
      />

      {error instanceof Error ? <ErrorAlert message={error.message} /> : null}

      {isLoading ? (
        <LoadingBlock label={t('superAdmin.audit.loading')} />
      ) : (data ?? []).length === 0 ? (
        <EmptyState
          title={t('superAdmin.audit.emptyTitle')}
          description={t('superAdmin.audit.emptyDescription')}
        />
      ) : (
        <div className="overflow-x-auto rounded-lg border border-[var(--color-border)] bg-white">
          <table className="min-w-full text-left text-sm">
            <thead className="bg-slate-50 text-xs uppercase text-[var(--color-muted)]">
              <tr>
                <th className="px-4 py-3">{t('superAdmin.audit.colWhen')}</th>
                <th className="px-4 py-3">{t('superAdmin.audit.colAction')}</th>
                <th className="px-4 py-3">{t('superAdmin.audit.colResource')}</th>
                <th className="px-4 py-3">{t('superAdmin.audit.colSummary')}</th>
                <th className="px-4 py-3">{t('superAdmin.audit.colCompany')}</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-[var(--color-border)]">
              {(data ?? []).map((entry) => (
                <tr key={entry.id}>
                  <td className="px-4 py-3 text-[var(--color-muted)]">
                    {new Date(entry.created_at).toLocaleString()}
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
                  <td className="px-4 py-3 text-[var(--color-muted)]">
                    {entry.company_id?.slice(0, 8) ?? t('common.emDash')}
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

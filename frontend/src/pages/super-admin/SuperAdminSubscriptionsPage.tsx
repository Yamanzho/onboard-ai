import { Link } from 'react-router-dom'
import { useQuery } from '@tanstack/react-query'
import {
  ErrorAlert,
  LoadingBlock,
  PageHeader,
} from '../../components/common/PageHeader'
import { usePlatformPaths } from '../../hooks/useWorkspacePaths'
import { t } from '../../i18n'
import * as superAdminApi from '../../services/superAdminApi'
import type { PlatformCompany } from '../../types/superAdmin'

export function SuperAdminSubscriptionsPage() {
  const paths = usePlatformPaths()
  const {
    data: companies = [],
    isLoading,
    error,
  } = useQuery({
    queryKey: ['super-admin-companies'],
    queryFn: () => superAdminApi.listCompanies(),
  })

  if (isLoading) return <LoadingBlock />
  if (error) {
    return (
      <ErrorAlert
        message={error instanceof Error ? error.message : t('common.actionFailed')}
      />
    )
  }

  return (
    <div>
      <PageHeader
        title={t('nav.subscriptions')}
        description={t('superAdmin.subscriptionsDescription')}
      />
      <div className="overflow-x-auto rounded-lg border border-[var(--color-border)] bg-white">
        <table className="min-w-full text-left text-sm">
          <thead className="bg-slate-50 text-xs uppercase text-[var(--color-muted)]">
            <tr>
              <th className="px-4 py-3">{t('common.name')}</th>
              <th className="px-4 py-3">{t('common.status')}</th>
              <th className="px-4 py-3" />
            </tr>
          </thead>
          <tbody className="divide-y divide-[var(--color-border)]">
            {companies.map((c: PlatformCompany) => (
              <tr key={c.id}>
                <td className="px-4 py-3 font-medium">{c.name}</td>
                <td className="px-4 py-3 text-[var(--color-muted)]">
                  {c.is_active
                    ? t('enums.companyStatus.active')
                    : t('enums.companyStatus.blocked')}
                </td>
                <td className="px-4 py-3 text-right">
                  <Link
                    to={paths.company(c.id)}
                    className="text-[var(--color-accent)] hover:underline"
                  >
                    {t('superAdmin.openSubscription')}
                  </Link>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  )
}

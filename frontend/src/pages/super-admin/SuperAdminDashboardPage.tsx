import {
  ErrorAlert,
  LoadingBlock,
  PageHeader,
} from '../../components/common/PageHeader'
import { usePlatformDashboard } from '../../hooks/useSuperAdmin'
import { useSuperAdminAuth } from '../../hooks/useSuperAdminAuth'
import { t } from '../../i18n'

export function SuperAdminDashboardPage() {
  const { user } = useSuperAdminAuth()
  const { data, isLoading, error } = usePlatformDashboard()

  return (
    <div>
      <PageHeader
        title={t('superAdmin.dashboard.title')}
        description={t('superAdmin.dashboard.description', {
          name: user?.full_name ?? t('superAdmin.dashboard.defaultUser'),
        })}
      />

      {error instanceof Error ? <ErrorAlert message={error.message} /> : null}

      {isLoading || !data ? (
        <LoadingBlock label={t('superAdmin.dashboard.loading')} />
      ) : (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-6">
          <StatCard label={t('superAdmin.dashboard.companies')} value={data.companies_count} />
          <StatCard label={t('superAdmin.dashboard.active')} value={data.active_companies} />
          <StatCard label={t('superAdmin.dashboard.trial')} value={data.trial_companies} />
          <StatCard label={t('superAdmin.dashboard.expired')} value={data.expired_companies} />
          <StatCard label={t('superAdmin.dashboard.employees')} value={data.employees_count} />
          <StatCard
            label={t('superAdmin.dashboard.activeAssignments')}
            value={data.active_assignments_count}
          />
        </div>
      )}
    </div>
  )
}

function StatCard({ label, value }: { label: string; value: number }) {
  return (
    <div className="rounded-lg border border-[var(--color-border)] bg-white px-4 py-4">
      <p className="text-xs uppercase tracking-wide text-[var(--color-muted)]">
        {label}
      </p>
      <p className="mt-1 text-2xl font-semibold">{value}</p>
    </div>
  )
}

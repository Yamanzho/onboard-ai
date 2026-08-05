import { PageHeader } from '../../components/common/PageHeader'
import { useAuth } from '../../hooks/useAuth'
import {
  labelEmployeeRole,
  labelEmployeeStatus,
  t,
} from '../../i18n'

export function SettingsPage() {
  const { user } = useAuth()

  return (
    <div>
      <PageHeader
        title={t('settings.title')}
        description={t('settings.description')}
      />
      <div className="max-w-lg rounded-lg border border-[var(--color-border)] bg-white p-5 text-sm">
        <dl className="space-y-3">
          <Row label={t('settings.name')} value={user?.full_name} />
          <Row label={t('common.email')} value={user?.email ?? t('common.emDash')} />
          <Row
            label={t('common.role')}
            value={user?.role ? labelEmployeeRole(user.role) : undefined}
          />
          <Row
            label={t('common.status')}
            value={user?.status ? labelEmployeeStatus(user.status) : undefined}
          />
          <Row label={t('settings.employeeId')} value={user?.id} />
          <Row label={t('settings.companyId')} value={user?.company_id} />
        </dl>
      </div>
    </div>
  )
}

function Row({ label, value }: { label: string; value?: string }) {
  return (
    <div>
      <dt className="text-xs uppercase tracking-wide text-[var(--color-muted)]">{label}</dt>
      <dd className="mt-0.5 break-all font-medium">{value}</dd>
    </div>
  )
}

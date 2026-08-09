import {
  ErrorAlert,
  LoadingBlock,
  PageHeader,
} from '../../components/common/PageHeader'
import { useAuth } from '../../hooks/useAuth'
import { t } from '../../i18n'

function formatDate(value: string | null | undefined) {
  if (!value) return t('common.emDash')
  try {
    return new Date(value).toLocaleDateString()
  } catch {
    return value
  }
}

export function MyCompanyPage() {
  const { user, loading } = useAuth()

  if (loading) return <LoadingBlock />
  if (!user) {
    return <ErrorAlert message={t('common.notFound')} />
  }

  const rows = [
    {
      label: t('employeePortal.companyName'),
      value: user.company_name ?? t('common.emDash'),
    },
    {
      label: t('employeePortal.companyDescription'),
      value: user.company_description?.trim() || t('common.emDash'),
    },
    {
      label: t('employeePortal.startDate'),
      value: formatDate(user.hired_at),
    },
  ]

  return (
    <div>
      <PageHeader
        title={t('employeePortal.companyTitle')}
        description={t('employeePortal.companyDescriptionPage')}
      />
      <div className="max-w-xl overflow-hidden rounded-lg border border-[var(--color-border)] bg-white">
        <dl className="divide-y divide-[var(--color-border)]">
          {rows.map((row) => (
            <div
              key={row.label}
              className="grid gap-1 px-4 py-3 sm:grid-cols-[12rem_1fr] sm:gap-4"
            >
              <dt className="text-sm text-[var(--color-muted)]">{row.label}</dt>
              <dd className="text-sm font-medium">{row.value}</dd>
            </div>
          ))}
        </dl>
      </div>
    </div>
  )
}

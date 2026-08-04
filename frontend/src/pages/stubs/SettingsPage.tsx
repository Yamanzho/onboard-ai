import { PageHeader } from '../../components/common/PageHeader'
import { useAuth } from '../../hooks/useAuth'

export function SettingsPage() {
  const { user } = useAuth()

  return (
    <div>
      <PageHeader
        title="Settings"
        description="Read-only profile for the signed-in user (MVP)."
      />
      <div className="max-w-lg rounded-lg border border-[var(--color-border)] bg-white p-5 text-sm">
        <dl className="space-y-3">
          <Row label="Name" value={user?.full_name} />
          <Row label="Email" value={user?.email ?? '—'} />
          <Row label="Role" value={user?.role} />
          <Row label="Status" value={user?.status} />
          <Row label="Employee ID" value={user?.id} />
          <Row label="Company ID" value={user?.company_id} />
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

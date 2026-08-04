import { PageHeader } from '../../components/common/PageHeader'

export function EmployeesPage() {
  return (
    <div>
      <PageHeader
        title="Employees"
        description="Coming in a later sprint."
      />
      <div className="rounded-lg border border-dashed border-[var(--color-border)] bg-white px-6 py-12 text-center text-sm text-[var(--color-muted)]">
        Employee management UI is not part of Sprint 2.3 MVP.
      </div>
    </div>
  )
}

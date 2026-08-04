import { PageHeader } from '../../components/common/PageHeader'

export function OnboardingPage() {
  return (
    <div>
      <PageHeader
        title="Onboarding"
        description="Coming in a later sprint."
      />
      <div className="rounded-lg border border-dashed border-[var(--color-border)] bg-white px-6 py-12 text-center text-sm text-[var(--color-muted)]">
        Programs, steps, and assignments UI will land in a later sprint.
      </div>
    </div>
  )
}

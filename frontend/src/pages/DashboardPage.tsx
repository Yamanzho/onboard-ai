import { Link } from 'react-router-dom'
import { PageHeader } from '../components/common/PageHeader'
import { StatusBadge } from '../components/knowledge/StatusBadge'
import { useArticles } from '../hooks/useArticles'
import { useAuth } from '../hooks/useAuth'

export function DashboardPage() {
  const { user } = useAuth()
  const { data, isLoading } = useArticles({ limit: 5 })

  const items = data?.items ?? []
  const draftCount = items.filter((a) => a.status === 'draft').length
  const publishedCount = items.filter((a) => a.status === 'published').length

  return (
    <div>
      <PageHeader
        title="Dashboard"
        description={`Welcome, ${user?.full_name}. Tenant ${user?.company_id}`}
      />

      <div className="mb-6 grid gap-4 sm:grid-cols-3">
        <StatCard label="Recent loaded" value={String(items.length)} />
        <StatCard label="Drafts (sample)" value={String(draftCount)} />
        <StatCard label="Published (sample)" value={String(publishedCount)} />
      </div>

      <div className="mb-6 grid gap-3 sm:grid-cols-3">
        <QuickLink to="/knowledge/articles" title="Knowledge Base" />
        <QuickLink to="/knowledge/categories" title="Categories" />
        <QuickLink to="/knowledge/tags" title="Tags" />
      </div>

      <section className="rounded-lg border border-[var(--color-border)] bg-white">
        <div className="border-b border-[var(--color-border)] px-4 py-3">
          <h2 className="text-sm font-semibold">Recent articles</h2>
        </div>
        {isLoading ? (
          <p className="px-4 py-6 text-sm text-[var(--color-muted)]">Loading…</p>
        ) : items.length === 0 ? (
          <p className="px-4 py-6 text-sm text-[var(--color-muted)]">
            No articles yet.{' '}
            <Link className="text-[var(--color-accent)] hover:underline" to="/knowledge/articles/new">
              Create one
            </Link>
          </p>
        ) : (
          <ul className="divide-y divide-[var(--color-border)]">
            {items.map((article) => (
              <li key={article.id} className="flex items-center justify-between gap-3 px-4 py-3">
                <Link
                  to={`/knowledge/articles/${article.id}`}
                  className="text-sm font-medium hover:text-[var(--color-accent)]"
                >
                  {article.current_version?.title ?? 'Untitled'}
                </Link>
                <StatusBadge status={article.status} />
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  )
}

function StatCard({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg border border-[var(--color-border)] bg-white px-4 py-4">
      <p className="text-xs uppercase tracking-wide text-[var(--color-muted)]">{label}</p>
      <p className="mt-1 text-2xl font-semibold">{value}</p>
    </div>
  )
}

function QuickLink({ to, title }: { to: string; title: string }) {
  return (
    <Link
      to={to}
      className="rounded-lg border border-[var(--color-border)] bg-white px-4 py-4 text-sm font-medium transition hover:border-[var(--color-accent)] hover:text-[var(--color-accent)]"
    >
      {title}
    </Link>
  )
}

import { useMemo, useState } from 'react'
import { Link } from 'react-router-dom'
import {
  EmptyState,
  ErrorAlert,
  LoadingBlock,
  PageHeader,
} from '../../components/common/PageHeader'
import { StatusBadge } from '../../components/knowledge/StatusBadge'
import { Button } from '../../components/ui/Button'
import { Select } from '../../components/ui/Field'
import { useArticleMutations, useArticles } from '../../hooks/useArticles'
import { useCategories } from '../../hooks/useCategories'
import { useTags } from '../../hooks/useTags'
import { ApiError } from '../../services/apiClient'

export function ArticleListPage() {
  const [status, setStatus] = useState('')
  const [categoryId, setCategoryId] = useState('')
  const [tagId, setTagId] = useState('')
  const [actionError, setActionError] = useState<string | null>(null)

  const filters = useMemo(
    () => ({
      status: status || undefined,
      category_id: categoryId || undefined,
      tag_id: tagId || undefined,
    }),
    [status, categoryId, tagId],
  )

  const { data, isLoading, error } = useArticles(filters)
  const { data: categories } = useCategories()
  const { data: tags } = useTags()
  const { publish, archive } = useArticleMutations()

  const items = data?.items ?? []

  async function onPublish(id: string) {
    setActionError(null)
    try {
      await publish.mutateAsync(id)
    } catch (err) {
      setActionError(err instanceof ApiError ? err.message : 'Publish failed')
    }
  }

  async function onArchive(id: string) {
    setActionError(null)
    try {
      await archive.mutateAsync(id)
    } catch (err) {
      setActionError(err instanceof ApiError ? err.message : 'Archive failed')
    }
  }

  return (
    <div>
      <PageHeader
        title="Knowledge Base"
        description="Manage company knowledge articles."
        action={
          <Link to="/knowledge/articles/new">
            <Button>New article</Button>
          </Link>
        }
      />

      {actionError ? <ErrorAlert message={actionError} /> : null}
      {error ? <ErrorAlert message={(error as Error).message} /> : null}

      <div className="mb-4 grid gap-3 rounded-lg border border-[var(--color-border)] bg-white p-4 md:grid-cols-3">
        <Select value={status} onChange={(e) => setStatus(e.target.value)}>
          <option value="">All statuses</option>
          <option value="draft">draft</option>
          <option value="published">published</option>
          <option value="archived">archived</option>
        </Select>
        <Select value={categoryId} onChange={(e) => setCategoryId(e.target.value)}>
          <option value="">All categories</option>
          {(categories ?? []).map((c) => (
            <option key={c.id} value={c.id}>
              {c.name}
            </option>
          ))}
        </Select>
        <Select value={tagId} onChange={(e) => setTagId(e.target.value)}>
          <option value="">All tags</option>
          {(tags ?? []).map((t) => (
            <option key={t.id} value={t.id}>
              {t.name}
            </option>
          ))}
        </Select>
      </div>

      {isLoading ? (
        <LoadingBlock />
      ) : items.length === 0 ? (
        <EmptyState
          title="No articles"
          description="Create your first knowledge article."
          actionLabel="Create article"
          actionTo="/knowledge/articles/new"
        />
      ) : (
        <div className="overflow-hidden rounded-lg border border-[var(--color-border)] bg-white">
          <table className="min-w-full text-left text-sm">
            <thead className="bg-slate-50 text-xs uppercase text-[var(--color-muted)]">
              <tr>
                <th className="px-4 py-3">Title</th>
                <th className="px-4 py-3">Status</th>
                <th className="px-4 py-3">Version</th>
                <th className="px-4 py-3">Tags</th>
                <th className="px-4 py-3" />
              </tr>
            </thead>
            <tbody className="divide-y divide-[var(--color-border)]">
              {items.map((article) => (
                <tr key={article.id}>
                  <td className="px-4 py-3">
                    <Link
                      to={`/knowledge/articles/${article.id}`}
                      className="font-medium hover:text-[var(--color-accent)]"
                    >
                      {article.current_version?.title ?? 'Untitled'}
                    </Link>
                  </td>
                  <td className="px-4 py-3">
                    <StatusBadge status={article.status} />
                  </td>
                  <td className="px-4 py-3 text-[var(--color-muted)]">
                    v{article.current_version?.version ?? '—'}
                  </td>
                  <td className="px-4 py-3 text-[var(--color-muted)]">
                    {article.tags.map((t) => t.name).join(', ') || '—'}
                  </td>
                  <td className="px-4 py-3">
                    <div className="flex justify-end gap-2">
                      {article.status === 'draft' ? (
                        <Button
                          variant="secondary"
                          onClick={() => void onPublish(article.id)}
                          disabled={publish.isPending}
                        >
                          Publish
                        </Button>
                      ) : null}
                      {article.status !== 'archived' ? (
                        <Button
                          variant="ghost"
                          onClick={() => void onArchive(article.id)}
                          disabled={archive.isPending}
                        >
                          Archive
                        </Button>
                      ) : null}
                    </div>
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

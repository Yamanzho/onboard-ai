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
import { useWorkspacePaths } from '../../hooks/useWorkspacePaths'
import { useCategories } from '../../hooks/useCategories'
import { useTags } from '../../hooks/useTags'
import { labelArticleStatus, t } from '../../i18n'
import { ApiError } from '../../services/apiClient'

const ARTICLE_STATUSES = ['draft', 'published', 'archived'] as const

export function ArticleListPage() {
  const paths = useWorkspacePaths()
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
      setActionError(
        err instanceof ApiError ? err.message : t('knowledge.articles.publishFailed'),
      )
    }
  }

  async function onArchive(id: string) {
    setActionError(null)
    try {
      await archive.mutateAsync(id)
    } catch (err) {
      setActionError(
        err instanceof ApiError ? err.message : t('knowledge.articles.archiveFailed'),
      )
    }
  }

  return (
    <div>
      <PageHeader
        title={t('knowledge.articles.title')}
        description={t('knowledge.articles.description')}
        action={
          <Link to={paths.knowledgeNew}>
            <Button>{t('knowledge.articles.new')}</Button>
          </Link>
        }
      />

      {actionError ? <ErrorAlert message={actionError} /> : null}
      {error ? <ErrorAlert message={(error as Error).message} /> : null}

      <div className="mb-4 grid gap-3 rounded-lg border border-[var(--color-border)] bg-white p-4 md:grid-cols-3">
        <Select value={status} onChange={(e) => setStatus(e.target.value)}>
          <option value="">{t('common.allStatuses')}</option>
          {ARTICLE_STATUSES.map((s) => (
            <option key={s} value={s}>
              {labelArticleStatus(s)}
            </option>
          ))}
        </Select>
        <Select value={categoryId} onChange={(e) => setCategoryId(e.target.value)}>
          <option value="">{t('knowledge.articles.allCategories')}</option>
          {(categories ?? []).map((c) => (
            <option key={c.id} value={c.id}>
              {c.name}
            </option>
          ))}
        </Select>
        <Select value={tagId} onChange={(e) => setTagId(e.target.value)}>
          <option value="">{t('knowledge.articles.allTags')}</option>
          {(tags ?? []).map((tag) => (
            <option key={tag.id} value={tag.id}>
              {tag.name}
            </option>
          ))}
        </Select>
      </div>

      {isLoading ? (
        <LoadingBlock />
      ) : items.length === 0 ? (
        <EmptyState
          title={t('knowledge.articles.emptyTitle')}
          description={t('knowledge.articles.emptyDescription')}
          actionLabel={t('knowledge.articles.create')}
          actionTo={paths.knowledgeNew}
        />
      ) : (
        <div className="overflow-hidden rounded-lg border border-[var(--color-border)] bg-white">
          <table className="min-w-full text-left text-sm">
            <thead className="bg-slate-50 text-xs uppercase text-[var(--color-muted)]">
              <tr>
                <th className="px-4 py-3">{t('knowledge.articles.colTitle')}</th>
                <th className="px-4 py-3">{t('common.status')}</th>
                <th className="px-4 py-3">{t('knowledge.articles.colVersion')}</th>
                <th className="px-4 py-3">{t('knowledge.articles.colTags')}</th>
                <th className="px-4 py-3" />
              </tr>
            </thead>
            <tbody className="divide-y divide-[var(--color-border)]">
              {items.map((article) => (
                <tr key={article.id}>
                  <td className="px-4 py-3">
                    <Link
                      to={paths.article(article.id)}
                      className="font-medium hover:text-[var(--color-accent)]"
                    >
                      {article.current_version?.title ?? t('knowledge.articles.untitled')}
                    </Link>
                  </td>
                  <td className="px-4 py-3">
                    <StatusBadge status={article.status} />
                  </td>
                  <td className="px-4 py-3 text-[var(--color-muted)]">
                    {article.current_version?.version != null
                      ? `${t('knowledge.articles.versionPrefix')}${article.current_version.version}`
                      : t('common.emDash')}
                  </td>
                  <td className="px-4 py-3 text-[var(--color-muted)]">
                    {article.tags.map((tag) => tag.name).join(', ') || t('common.emDash')}
                  </td>
                  <td className="px-4 py-3">
                    <div className="flex justify-end gap-2">
                      {article.status === 'draft' ? (
                        <Button
                          variant="secondary"
                          onClick={() => void onPublish(article.id)}
                          disabled={publish.isPending}
                        >
                          {t('common.publish')}
                        </Button>
                      ) : null}
                      {article.status !== 'archived' ? (
                        <Button
                          variant="ghost"
                          onClick={() => void onArchive(article.id)}
                          disabled={archive.isPending}
                        >
                          {t('common.archive')}
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

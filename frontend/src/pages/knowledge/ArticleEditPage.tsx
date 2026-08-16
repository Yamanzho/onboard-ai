import { useState } from 'react'
import { Link, useParams } from 'react-router-dom'
import {
  EmptyState,
  ErrorAlert,
  LoadingBlock,
  PageHeader,
} from '../../components/common/PageHeader'
import {
  ArticleForm,
  type ArticleFormValues,
} from '../../components/knowledge/ArticleForm'
import { StatusBadge } from '../../components/knowledge/StatusBadge'
import { Button } from '../../components/ui/Button'
import { useArticle, useArticleMutations, useArticleVersion, useArticleVersions } from '../../hooks/useArticles'
import { useWorkspacePaths } from '../../hooks/useWorkspacePaths'
import { useCategories } from '../../hooks/useCategories'
import { useTags } from '../../hooks/useTags'
import { usePrograms } from '../../hooks/usePrograms'
import { t } from '../../i18n'
import { ApiError } from '../../services/apiClient'

export function ArticleEditPage() {
  const { articleId } = useParams<{ articleId: string }>()
  const paths = useWorkspacePaths()
  const { data: article, isLoading, error } = useArticle(articleId)
  const { data: categories = [] } = useCategories()
  const { data: tags = [] } = useTags()
  const { data: programs = [] } = usePrograms()
  const { update, publish, archive, restoreVersion } = useArticleMutations()
  const { data: versions } = useArticleVersions(articleId)
  const [viewVersion, setViewVersion] = useState<number | undefined>(undefined)
  const { data: historical, isLoading: historicalLoading } = useArticleVersion(
    articleId,
    viewVersion,
  )

  async function onSubmit(values: ArticleFormValues) {
    if (!articleId) return
    try {
      await update.mutateAsync({
        id: articleId,
        payload: {
          title: values.title.trim(),
          body: values.body,
          category_id: values.category_id || null,
          visibility: values.visibility,
          tag_ids: values.tag_ids,
          program_ids: values.program_ids,
          change_summary: values.change_summary.trim() || null,
        },
      })
    } catch (err) {
      throw new Error(
        err instanceof ApiError ? err.message : t('knowledge.articles.updateFailed'),
      )
    }
  }

  if (isLoading) return <LoadingBlock />
  if (error || !article) {
    return (
      <ErrorAlert
        message={
          error instanceof Error ? error.message : t('knowledge.articles.notFound')
        }
      />
    )
  }

  const version = article.current_version

  return (
    <div>
      <PageHeader
        title={version?.title ?? t('knowledge.articles.editTitle')}
        description={t('knowledge.articles.editDescription')}
        action={
          <Link to={paths.knowledge}>
            <Button variant="secondary">{t('common.back')}</Button>
          </Link>
        }
      />

      <div className="mb-4 flex flex-wrap items-center gap-3 rounded-lg border border-[var(--color-border)] bg-white px-4 py-3 text-sm">
        <StatusBadge status={article.status} />
        <span className="text-[var(--color-muted)]">
          {t('knowledge.articles.currentVersion')}:{' '}
          <strong>
            {version?.version != null
              ? `${t('knowledge.articles.versionPrefix')}${version.version}`
              : t('common.emDash')}
          </strong>
        </span>
        {version?.change_summary ? (
          <span className="text-[var(--color-muted)]">
            {t('knowledge.articles.summary')}: {version.change_summary}
          </span>
        ) : null}
        <div className="ml-auto flex gap-2">
          {article.status === 'draft' ? (
            <Button
              variant="secondary"
              disabled={publish.isPending}
              onClick={() => {
                const title = version?.title ?? t('knowledge.articles.untitled')
                if (!window.confirm(t('knowledge.articles.publishConfirm', { title }))) {
                  return
                }
                void publish.mutateAsync(article.id)
              }}
            >
              {t('common.publish')}
            </Button>
          ) : null}
          {article.status !== 'archived' ? (
            <Button
              variant="ghost"
              disabled={archive.isPending}
              onClick={() => {
                const title = version?.title ?? t('knowledge.articles.untitled')
                if (!window.confirm(t('knowledge.articles.archiveConfirm', { title }))) {
                  return
                }
                void archive.mutateAsync(article.id)
              }}
            >
              {t('common.archive')}
            </Button>
          ) : null}
        </div>
      </div>

      <div className="rounded-lg border border-[var(--color-border)] bg-white p-5">
        <ArticleForm
          key={`${article.id}-${article.current_version_id}`}
          initial={{
            title: version?.title ?? '',
            body: version?.body ?? '',
            category_id: article.category_id ?? '',
            visibility: (article.visibility as 'company' | 'program') ?? 'company',
            tag_ids: article.tags.map((tag) => tag.id),
            program_ids: article.program_ids ?? [],
            change_summary: '',
          }}
          categories={categories}
          tags={tags}
          programs={programs}
          submitLabel={t('common.save')}
          pending={update.isPending}
          onSubmit={onSubmit}
        />
      </div>

      <section className="mt-6 rounded-lg border border-[var(--color-border)] bg-white p-5">
        <h2 className="mb-3 text-lg font-semibold">
          {t('knowledge.articles.historyTitle')}
        </h2>
        {(versions?.items ?? []).length === 0 ? (
          <EmptyState title={t('knowledge.articles.historyEmpty')} />
        ) : (
          <div className="overflow-x-auto">
            <table className="min-w-full text-left text-sm">
              <thead className="bg-slate-50 text-xs uppercase text-[var(--color-muted)]">
                <tr>
                  <th className="px-3 py-2">{t('knowledge.articles.colVersion')}</th>
                  <th className="px-3 py-2">{t('companyAudit.colWhen')}</th>
                  <th className="px-3 py-2">{t('knowledge.articles.summary')}</th>
                  <th className="px-3 py-2" />
                </tr>
              </thead>
              <tbody className="divide-y divide-[var(--color-border)]">
                {(versions?.items ?? []).map((row) => (
                  <tr key={row.id}>
                    <td className="px-3 py-2 font-medium">
                      {t('knowledge.articles.versionPrefix')}
                      {row.version}
                      {row.id === article.current_version_id
                        ? ` · ${t('knowledge.articles.current')}`
                        : ''}
                    </td>
                    <td className="px-3 py-2 text-[var(--color-muted)]">
                      {new Date(row.created_at).toLocaleString()}
                    </td>
                    <td className="px-3 py-2">
                      {row.change_summary ?? t('common.emDash')}
                    </td>
                    <td className="px-3 py-2">
                      <div className="flex flex-wrap gap-2">
                        <Button
                          variant="secondary"
                          onClick={() => setViewVersion(row.version)}
                        >
                          {t('knowledge.articles.viewVersion')}
                        </Button>
                        {row.id !== article.current_version_id &&
                        article.status !== 'archived' ? (
                          <Button
                            variant="ghost"
                            disabled={restoreVersion.isPending}
                            onClick={() => {
                              if (
                                !window.confirm(
                                  t('knowledge.articles.restoreConfirm', {
                                    version: String(row.version),
                                  }),
                                )
                              ) {
                                return
                              }
                              void restoreVersion.mutateAsync({
                                id: article.id,
                                version: row.version,
                              })
                            }}
                          >
                            {t('knowledge.articles.restore')}
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
        {viewVersion != null ? (
          <div className="mt-4 rounded-md border border-[var(--color-border)] bg-[var(--color-bg)] p-4">
            <div className="mb-2 flex items-center justify-between gap-2">
              <h3 className="font-medium">
                {t('knowledge.articles.versionPrefix')}
                {viewVersion}
              </h3>
              <Button variant="ghost" onClick={() => setViewVersion(undefined)}>
                {t('common.close')}
              </Button>
            </div>
            {historicalLoading ? (
              <LoadingBlock />
            ) : historical ? (
              <div className="space-y-2 text-sm">
                <p className="font-medium">{historical.title}</p>
                <pre className="max-h-80 overflow-auto whitespace-pre-wrap break-words rounded bg-white p-3">
                  {historical.body}
                </pre>
              </div>
            ) : (
              <ErrorAlert message={t('knowledge.articles.notFound')} />
            )}
          </div>
        ) : null}
      </section>
    </div>
  )
}

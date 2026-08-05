import { Link, useParams } from 'react-router-dom'
import {
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
import { useArticle, useArticleMutations } from '../../hooks/useArticles'
import { useCategories } from '../../hooks/useCategories'
import { useTags } from '../../hooks/useTags'
import { t } from '../../i18n'
import { ApiError } from '../../services/apiClient'

export function ArticleEditPage() {
  const { articleId } = useParams<{ articleId: string }>()
  const { data: article, isLoading, error } = useArticle(articleId)
  const { data: categories = [] } = useCategories()
  const { data: tags = [] } = useTags()
  const { update, publish, archive } = useArticleMutations()

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
          <Link to="/knowledge/articles">
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
              onClick={() => void publish.mutateAsync(article.id)}
            >
              {t('common.publish')}
            </Button>
          ) : null}
          {article.status !== 'archived' ? (
            <Button
              variant="ghost"
              disabled={archive.isPending}
              onClick={() => void archive.mutateAsync(article.id)}
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
            change_summary: '',
          }}
          categories={categories}
          tags={tags}
          submitLabel={t('common.save')}
          pending={update.isPending}
          onSubmit={onSubmit}
        />
      </div>
    </div>
  )
}

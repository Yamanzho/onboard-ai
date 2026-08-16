import { Link, useParams } from 'react-router-dom'
import {
  ErrorAlert,
  LoadingBlock,
  PageHeader,
} from '../../components/common/PageHeader'
import { Button } from '../../components/ui/Button'
import { useArticle } from '../../hooks/useArticles'
import { useWorkspacePaths } from '../../hooks/useWorkspacePaths'
import { t } from '../../i18n'

export function EmployeeArticlePage() {
  const { articleId } = useParams<{ articleId: string }>()
  const paths = useWorkspacePaths()
  const { data: article, isLoading, error, refetch } = useArticle(articleId)

  if (isLoading) return <LoadingBlock />
  if (error || !article) {
    return (
      <ErrorAlert
        message={
          error instanceof Error ? error.message : t('knowledge.articles.notFound')
        }
        onRetry={() => void refetch()}
      />
    )
  }

  const version = article.current_version

  return (
    <div>
      <PageHeader
        title={version?.title ?? t('knowledge.articles.untitled')}
        description={t('employeePortal.kbArticleDescription')}
        action={
          <Link to={paths.knowledge}>
            <Button variant="secondary">{t('common.back')}</Button>
          </Link>
        }
      />
      {article.tags.length > 0 ? (
        <p className="mb-4 text-sm text-[var(--color-muted)]">
          {article.tags.map((tag) => tag.name).join(', ')}
        </p>
      ) : null}
      <div className="max-w-3xl whitespace-pre-wrap rounded-lg border border-[var(--color-border)] bg-white p-5 text-sm leading-6">
        {version?.body || t('common.noData')}
      </div>
    </div>
  )
}

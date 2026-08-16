import { useState } from 'react'
import { Link } from 'react-router-dom'
import {
  EmptyState,
  ErrorAlert,
  LoadingBlock,
  PageHeader,
} from '../../components/common/PageHeader'
import { Input } from '../../components/ui/Field'
import { useArticles } from '../../hooks/useArticles'
import { useWorkspacePaths } from '../../hooks/useWorkspacePaths'
import { t } from '../../i18n'

export function EmployeeKnowledgeListPage() {
  const paths = useWorkspacePaths()
  const [search, setSearch] = useState('')
  const { data, isLoading, error, refetch } = useArticles({
    status: 'published',
    q: search.trim() || undefined,
  })
  const items = data?.items ?? []

  return (
    <div>
      <PageHeader
        title={t('employeePortal.kbTitle')}
        description={t('employeePortal.kbDescription')}
      />
      {error ? (
        <ErrorAlert
          message={(error as Error).message}
          onRetry={() => void refetch()}
        />
      ) : null}
      <div className="mb-4">
        <Input
          value={search}
          onChange={(e) => setSearch(e.target.value)}
          placeholder={t('employeePortal.kbSearch')}
          aria-label={t('employeePortal.kbSearch')}
        />
      </div>
      {isLoading ? (
        <LoadingBlock />
      ) : items.length === 0 ? (
        <EmptyState
          title={
            search.trim()
              ? t('knowledge.articles.searchEmptyTitle')
              : t('employeePortal.kbEmptyTitle')
          }
          description={
            search.trim()
              ? t('knowledge.articles.searchEmptyDescription')
              : t('employeePortal.kbEmptyDescription')
          }
        />
      ) : (
        <ul className="space-y-3">
          {items.map((article) => (
            <li
              key={article.id}
              className="rounded-lg border border-[var(--color-border)] bg-white p-4"
            >
              <Link
                to={`${paths.knowledge}/${article.id}`}
                className="font-medium hover:text-[var(--color-accent)]"
              >
                {article.current_version?.title ?? t('knowledge.articles.untitled')}
              </Link>
              {article.tags.length > 0 ? (
                <p className="mt-1 text-sm text-[var(--color-muted)]">
                  {article.tags.map((tag) => tag.name).join(', ')}
                </p>
              ) : null}
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

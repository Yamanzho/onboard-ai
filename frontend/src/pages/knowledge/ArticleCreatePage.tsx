import { useNavigate } from 'react-router-dom'
import { ErrorAlert, PageHeader } from '../../components/common/PageHeader'
import {
  ArticleForm,
  type ArticleFormValues,
} from '../../components/knowledge/ArticleForm'
import { useArticleMutations } from '../../hooks/useArticles'
import { useWorkspacePaths } from '../../hooks/useWorkspacePaths'
import { useCategories } from '../../hooks/useCategories'
import { useTags } from '../../hooks/useTags'
import { usePrograms } from '../../hooks/usePrograms'
import { t } from '../../i18n'
import { ApiError } from '../../services/apiClient'

export function ArticleCreatePage() {
  const navigate = useNavigate()
  const paths = useWorkspacePaths()
  const { data: categories = [] } = useCategories()
  const { data: tags = [] } = useTags()
  const { data: programs = [] } = usePrograms()
  const { create } = useArticleMutations()

  async function onSubmit(values: ArticleFormValues) {
    try {
      const article = await create.mutateAsync({
        title: values.title.trim(),
        body: values.body,
        body_format: 'markdown',
        category_id: values.category_id || null,
        visibility: values.visibility,
        tag_ids: values.tag_ids,
        program_ids: values.program_ids,
        change_summary: values.change_summary.trim() || null,
      })
      navigate(paths.article(article.id))
    } catch (err) {
      throw new Error(
        err instanceof ApiError ? err.message : t('knowledge.articles.createFailed'),
      )
    }
  }

  return (
    <div>
      <PageHeader
        title={t('knowledge.articles.createTitle')}
        description={t('knowledge.articles.createDescription')}
      />
      {create.isError ? (
        <ErrorAlert
          message={
            create.error instanceof Error
              ? create.error.message
              : t('knowledge.articles.createFailed')
          }
        />
      ) : null}
      <div className="rounded-lg border border-[var(--color-border)] bg-white p-5">
        <ArticleForm
          initial={{
            title: '',
            body: '',
            category_id: '',
            visibility: 'company',
            tag_ids: [],
            program_ids: [],
            change_summary: t('knowledge.articles.initialDraft'),
          }}
          categories={categories}
          tags={tags}
          programs={programs}
          submitLabel={t('knowledge.articles.createDraft')}
          pending={create.isPending}
          onSubmit={onSubmit}
        />
      </div>
    </div>
  )
}

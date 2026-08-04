import { useNavigate } from 'react-router-dom'
import { ErrorAlert, PageHeader } from '../../components/common/PageHeader'
import {
  ArticleForm,
  type ArticleFormValues,
} from '../../components/knowledge/ArticleForm'
import { useArticleMutations } from '../../hooks/useArticles'
import { useCategories } from '../../hooks/useCategories'
import { useTags } from '../../hooks/useTags'
import { ApiError } from '../../services/apiClient'

export function ArticleCreatePage() {
  const navigate = useNavigate()
  const { data: categories = [] } = useCategories()
  const { data: tags = [] } = useTags()
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
        change_summary: values.change_summary.trim() || null,
      })
      navigate(`/knowledge/articles/${article.id}`)
    } catch (err) {
      throw new Error(err instanceof ApiError ? err.message : 'Failed to create article')
    }
  }

  return (
    <div>
      <PageHeader
        title="Create article"
        description="New articles start as drafts (version 1)."
      />
      {create.isError ? (
        <ErrorAlert
          message={
            create.error instanceof Error ? create.error.message : 'Create failed'
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
            change_summary: 'Initial draft',
          }}
          categories={categories}
          tags={tags}
          submitLabel="Create draft"
          pending={create.isPending}
          onSubmit={onSubmit}
        />
      </div>
    </div>
  )
}

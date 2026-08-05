import { useMemo, useState, type FormEvent, type ReactNode } from 'react'
import { Button } from '../ui/Button'
import { Input, Label, Select, Textarea } from '../ui/Field'
import { labelVisibility, t } from '../../i18n'
import type { Category } from '../../types/category'
import type { Tag } from '../../types/tag'
import type { KnowledgeVisibility } from '../../types/article'

export interface ArticleFormValues {
  title: string
  body: string
  category_id: string
  visibility: KnowledgeVisibility
  tag_ids: string[]
  change_summary: string
}

interface ArticleFormProps {
  initial: ArticleFormValues
  categories: Category[]
  tags: Tag[]
  submitLabel: string
  pending?: boolean
  onSubmit: (values: ArticleFormValues) => Promise<void>
  extraActions?: ReactNode
}

const VISIBILITY_OPTIONS: KnowledgeVisibility[] = ['company', 'program']

export function ArticleForm({
  initial,
  categories,
  tags,
  submitLabel,
  pending,
  onSubmit,
  extraActions,
}: ArticleFormProps) {
  const [values, setValues] = useState(initial)
  const [error, setError] = useState<string | null>(null)

  const selected = useMemo(() => new Set(values.tag_ids), [values.tag_ids])

  function toggleTag(id: string) {
    setValues((prev) => {
      const next = new Set(prev.tag_ids)
      if (next.has(id)) next.delete(id)
      else next.add(id)
      return { ...prev, tag_ids: [...next] }
    })
  }

  async function handleSubmit(e: FormEvent) {
    e.preventDefault()
    setError(null)
    try {
      await onSubmit(values)
    } catch (err) {
      setError(err instanceof Error ? err.message : t('common.saveFailed'))
    }
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-4">
      {error ? (
        <div className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-800">
          {error}
        </div>
      ) : null}

      <div>
        <Label htmlFor="title">{t('knowledge.articles.colTitle')}</Label>
        <Input
          id="title"
          value={values.title}
          onChange={(e) => setValues({ ...values, title: e.target.value })}
          required
        />
      </div>

      <div>
        <Label htmlFor="body">{t('knowledge.articles.body')}</Label>
        <Textarea
          id="body"
          rows={12}
          value={values.body}
          onChange={(e) => setValues({ ...values, body: e.target.value })}
          required
        />
      </div>

      <div className="grid gap-4 md:grid-cols-2">
        <div>
          <Label htmlFor="category">{t('knowledge.articles.category')}</Label>
          <Select
            id="category"
            value={values.category_id}
            onChange={(e) => setValues({ ...values, category_id: e.target.value })}
          >
            <option value="">{t('knowledge.articles.none')}</option>
            {categories.map((c) => (
              <option key={c.id} value={c.id}>
                {c.name}
              </option>
            ))}
          </Select>
        </div>
        <div>
          <Label htmlFor="visibility">{t('knowledge.articles.visibility')}</Label>
          <Select
            id="visibility"
            value={values.visibility}
            onChange={(e) =>
              setValues({
                ...values,
                visibility: e.target.value as KnowledgeVisibility,
              })
            }
          >
            {VISIBILITY_OPTIONS.map((v) => (
              <option key={v} value={v}>
                {labelVisibility(v)}
              </option>
            ))}
          </Select>
        </div>
      </div>

      <div>
        <Label>{t('knowledge.articles.tags')}</Label>
        <div className="mt-1 flex flex-wrap gap-2">
          {tags.length === 0 ? (
            <p className="text-sm text-[var(--color-muted)]">
              {t('knowledge.articles.noTags')}
            </p>
          ) : (
            tags.map((tag) => {
              const on = selected.has(tag.id)
              return (
                <button
                  key={tag.id}
                  type="button"
                  onClick={() => toggleTag(tag.id)}
                  className={`rounded-full border px-3 py-1 text-xs font-medium ${
                    on
                      ? 'border-[var(--color-accent)] bg-teal-50 text-[var(--color-accent)]'
                      : 'border-[var(--color-border)] bg-white text-[var(--color-muted)]'
                  }`}
                >
                  {tag.name}
                </button>
              )
            })
          )}
        </div>
      </div>

      <div>
        <Label htmlFor="summary">{t('knowledge.articles.summary')}</Label>
        <Input
          id="summary"
          value={values.change_summary}
          onChange={(e) => setValues({ ...values, change_summary: e.target.value })}
          placeholder={t('knowledge.articles.changeSummaryPlaceholder')}
        />
      </div>

      <div className="flex flex-wrap items-center gap-2">
        <Button type="submit" disabled={pending}>
          {pending ? t('common.saving') : submitLabel}
        </Button>
        {extraActions}
      </div>
    </form>
  )
}

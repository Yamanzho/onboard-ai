import { useState, type FormEvent } from 'react'
import {
  EmptyState,
  ErrorAlert,
  LoadingBlock,
  PageHeader,
} from '../../components/common/PageHeader'
import { Button } from '../../components/ui/Button'
import { Input, Label } from '../../components/ui/Field'
import { useTagMutations, useTags } from '../../hooks/useTags'
import { t } from '../../i18n'
import { ApiError } from '../../services/apiClient'
import type { Tag } from '../../types/tag'

export function TagsPage() {
  const { data, isLoading, error } = useTags()
  const { create, update } = useTagMutations()
  const [name, setName] = useState('')
  const [slug, setSlug] = useState('')
  const [formError, setFormError] = useState<string | null>(null)
  const [editing, setEditing] = useState<Tag | null>(null)

  const tags = data ?? []

  async function onCreate(e: FormEvent) {
    e.preventDefault()
    setFormError(null)
    try {
      await create.mutateAsync({
        name: name.trim(),
        slug: slug.trim() || null,
      })
      setName('')
      setSlug('')
    } catch (err) {
      setFormError(
        err instanceof ApiError ? err.message : t('knowledge.tags.createFailed'),
      )
    }
  }

  async function onSaveEdit(e: FormEvent) {
    e.preventDefault()
    if (!editing) return
    setFormError(null)
    try {
      await update.mutateAsync({
        id: editing.id,
        payload: {
          name: editing.name.trim(),
          slug: editing.slug.trim() || null,
        },
      })
      setEditing(null)
    } catch (err) {
      setFormError(
        err instanceof ApiError ? err.message : t('knowledge.tags.updateFailed'),
      )
    }
  }

  return (
    <div>
      <PageHeader
        title={t('knowledge.tags.title')}
        description={t('knowledge.tags.description')}
      />
      {formError ? <ErrorAlert message={formError} /> : null}
      {error ? <ErrorAlert message={(error as Error).message} /> : null}

      <form
        onSubmit={onCreate}
        className="mb-6 grid gap-3 rounded-lg border border-[var(--color-border)] bg-white p-4 md:grid-cols-3"
      >
        <div>
          <Label htmlFor="tag-name">{t('common.name')}</Label>
          <Input
            id="tag-name"
            value={name}
            onChange={(e) => setName(e.target.value)}
            required
          />
        </div>
        <div>
          <Label htmlFor="tag-slug">{t('knowledge.tags.slugOptional')}</Label>
          <Input
            id="tag-slug"
            value={slug}
            onChange={(e) => setSlug(e.target.value)}
            placeholder={t('knowledge.tags.slugPlaceholder')}
          />
        </div>
        <div className="flex items-end">
          <Button type="submit" disabled={create.isPending} className="w-full">
            {create.isPending ? t('common.creating') : t('knowledge.tags.create')}
          </Button>
        </div>
      </form>

      {isLoading ? (
        <LoadingBlock />
      ) : tags.length === 0 ? (
        <EmptyState
          title={t('knowledge.tags.emptyTitle')}
          description={t('knowledge.tags.emptyDescription')}
        />
      ) : (
        <div className="overflow-hidden rounded-lg border border-[var(--color-border)] bg-white">
          <table className="min-w-full text-left text-sm">
            <thead className="bg-slate-50 text-xs uppercase text-[var(--color-muted)]">
              <tr>
                <th className="px-4 py-3">{t('knowledge.tags.colName')}</th>
                <th className="px-4 py-3">{t('knowledge.tags.colSlug')}</th>
                <th className="px-4 py-3" />
              </tr>
            </thead>
            <tbody className="divide-y divide-[var(--color-border)]">
              {tags.map((tag) => (
                <tr key={tag.id}>
                  <td className="px-4 py-3 font-medium">{tag.name}</td>
                  <td className="px-4 py-3 text-[var(--color-muted)]">{tag.slug}</td>
                  <td className="px-4 py-3 text-right">
                    <Button variant="secondary" onClick={() => setEditing(tag)}>
                      {t('common.edit')}
                    </Button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {editing ? (
        <div className="fixed inset-0 z-20 flex items-center justify-center bg-black/40 p-4">
          <form
            onSubmit={onSaveEdit}
            className="w-full max-w-md rounded-lg bg-white p-5 shadow-lg"
          >
            <h2 className="mb-4 text-lg font-semibold">{t('knowledge.tags.editTitle')}</h2>
            <div className="mb-3">
              <Label>{t('common.name')}</Label>
              <Input
                value={editing.name}
                onChange={(e) => setEditing({ ...editing, name: e.target.value })}
                required
              />
            </div>
            <div className="mb-4">
              <Label>{t('common.slug')}</Label>
              <Input
                value={editing.slug}
                onChange={(e) => setEditing({ ...editing, slug: e.target.value })}
              />
            </div>
            <div className="flex justify-end gap-2">
              <Button type="button" variant="secondary" onClick={() => setEditing(null)}>
                {t('common.cancel')}
              </Button>
              <Button type="submit" disabled={update.isPending}>
                {t('common.save')}
              </Button>
            </div>
          </form>
        </div>
      ) : null}
    </div>
  )
}

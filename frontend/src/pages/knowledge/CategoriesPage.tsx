import { useState, type FormEvent } from 'react'
import {
  EmptyState,
  ErrorAlert,
  LoadingBlock,
  PageHeader,
} from '../../components/common/PageHeader'
import { Button } from '../../components/ui/Button'
import { Input, Label, Select } from '../../components/ui/Field'
import { useCategories, useCategoryMutations } from '../../hooks/useCategories'
import { t } from '../../i18n'
import { ApiError } from '../../services/apiClient'
import type { Category } from '../../types/category'

export function CategoriesPage() {
  const { data, isLoading, error } = useCategories()
  const { create, update } = useCategoryMutations()
  const [name, setName] = useState('')
  const [slug, setSlug] = useState('')
  const [parentId, setParentId] = useState('')
  const [formError, setFormError] = useState<string | null>(null)
  const [editing, setEditing] = useState<Category | null>(null)

  const categories = data ?? []

  async function onCreate(e: FormEvent) {
    e.preventDefault()
    setFormError(null)
    try {
      await create.mutateAsync({
        name: name.trim(),
        slug: slug.trim() || null,
        parent_id: parentId || null,
      })
      setName('')
      setSlug('')
      setParentId('')
    } catch (err) {
      setFormError(
        err instanceof ApiError ? err.message : t('knowledge.categories.createFailed'),
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
          parent_id: editing.parent_id,
          position: editing.position,
        },
      })
      setEditing(null)
    } catch (err) {
      setFormError(
        err instanceof ApiError ? err.message : t('knowledge.categories.updateFailed'),
      )
    }
  }

  return (
    <div>
      <PageHeader
        title={t('knowledge.categories.title')}
        description={t('knowledge.categories.description')}
      />
      {formError ? <ErrorAlert message={formError} /> : null}
      {error ? <ErrorAlert message={(error as Error).message} /> : null}

      <form
        onSubmit={onCreate}
        className="mb-6 grid gap-3 rounded-lg border border-[var(--color-border)] bg-white p-4 md:grid-cols-4"
      >
        <div>
          <Label htmlFor="cat-name">{t('common.name')}</Label>
          <Input
            id="cat-name"
            value={name}
            onChange={(e) => setName(e.target.value)}
            required
          />
        </div>
        <div>
          <Label htmlFor="cat-slug">{t('knowledge.categories.slugOptional')}</Label>
          <Input
            id="cat-slug"
            value={slug}
            onChange={(e) => setSlug(e.target.value)}
            placeholder={t('knowledge.categories.slugPlaceholder')}
          />
        </div>
        <div>
          <Label htmlFor="cat-parent">{t('knowledge.categories.parent')}</Label>
          <Select
            id="cat-parent"
            value={parentId}
            onChange={(e) => setParentId(e.target.value)}
          >
            <option value="">{t('knowledge.categories.none')}</option>
            {categories.map((c) => (
              <option key={c.id} value={c.id}>
                {c.name}
              </option>
            ))}
          </Select>
        </div>
        <div className="flex items-end">
          <Button type="submit" disabled={create.isPending} className="w-full">
            {create.isPending ? t('common.creating') : t('knowledge.categories.create')}
          </Button>
        </div>
      </form>

      {isLoading ? (
        <LoadingBlock />
      ) : categories.length === 0 ? (
        <EmptyState
          title={t('knowledge.categories.emptyTitle')}
          description={t('knowledge.categories.emptyDescription')}
        />
      ) : (
        <div className="overflow-hidden rounded-lg border border-[var(--color-border)] bg-white">
          <table className="min-w-full text-left text-sm">
            <thead className="bg-slate-50 text-xs uppercase text-[var(--color-muted)]">
              <tr>
                <th className="px-4 py-3">{t('knowledge.categories.colName')}</th>
                <th className="px-4 py-3">{t('knowledge.categories.colSlug')}</th>
                <th className="px-4 py-3">{t('knowledge.categories.colParent')}</th>
                <th className="px-4 py-3">{t('knowledge.categories.colPosition')}</th>
                <th className="px-4 py-3" />
              </tr>
            </thead>
            <tbody className="divide-y divide-[var(--color-border)]">
              {categories.map((c) => (
                <tr key={c.id}>
                  <td className="px-4 py-3 font-medium">{c.name}</td>
                  <td className="px-4 py-3 text-[var(--color-muted)]">{c.slug}</td>
                  <td className="px-4 py-3 text-[var(--color-muted)]">
                    {categories.find((p) => p.id === c.parent_id)?.name ?? t('common.emDash')}
                  </td>
                  <td className="px-4 py-3">{c.position}</td>
                  <td className="px-4 py-3 text-right">
                    <Button variant="secondary" onClick={() => setEditing(c)}>
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
            <h2 className="mb-4 text-lg font-semibold">
              {t('knowledge.categories.editTitle')}
            </h2>
            <div className="mb-3">
              <Label>{t('common.name')}</Label>
              <Input
                value={editing.name}
                onChange={(e) => setEditing({ ...editing, name: e.target.value })}
                required
              />
            </div>
            <div className="mb-3">
              <Label>{t('common.slug')}</Label>
              <Input
                value={editing.slug}
                onChange={(e) => setEditing({ ...editing, slug: e.target.value })}
              />
            </div>
            <div className="mb-3">
              <Label>{t('knowledge.categories.parent')}</Label>
              <Select
                value={editing.parent_id ?? ''}
                onChange={(e) =>
                  setEditing({
                    ...editing,
                    parent_id: e.target.value || null,
                  })
                }
              >
                <option value="">{t('knowledge.categories.none')}</option>
                {categories
                  .filter((c) => c.id !== editing.id)
                  .map((c) => (
                    <option key={c.id} value={c.id}>
                      {c.name}
                    </option>
                  ))}
              </Select>
            </div>
            <div className="mb-4">
              <Label>{t('knowledge.categories.colPosition')}</Label>
              <Input
                type="number"
                min={0}
                value={editing.position}
                onChange={(e) =>
                  setEditing({
                    ...editing,
                    position: Number(e.target.value) || 0,
                  })
                }
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

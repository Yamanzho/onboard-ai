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
      setFormError(err instanceof ApiError ? err.message : 'Failed to create tag')
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
      setFormError(err instanceof ApiError ? err.message : 'Failed to update tag')
    }
  }

  return (
    <div>
      <PageHeader title="Tags" description="Label articles for filtering and discovery." />
      {formError ? <ErrorAlert message={formError} /> : null}
      {error ? <ErrorAlert message={(error as Error).message} /> : null}

      <form
        onSubmit={onCreate}
        className="mb-6 grid gap-3 rounded-lg border border-[var(--color-border)] bg-white p-4 md:grid-cols-3"
      >
        <div>
          <Label htmlFor="tag-name">Name</Label>
          <Input
            id="tag-name"
            value={name}
            onChange={(e) => setName(e.target.value)}
            required
          />
        </div>
        <div>
          <Label htmlFor="tag-slug">Slug (optional)</Label>
          <Input
            id="tag-slug"
            value={slug}
            onChange={(e) => setSlug(e.target.value)}
            placeholder="auto from name"
          />
        </div>
        <div className="flex items-end">
          <Button type="submit" disabled={create.isPending} className="w-full">
            {create.isPending ? 'Creating…' : 'Create'}
          </Button>
        </div>
      </form>

      {isLoading ? (
        <LoadingBlock />
      ) : tags.length === 0 ? (
        <EmptyState title="No tags yet" description="Create tags like vacation or security." />
      ) : (
        <div className="overflow-hidden rounded-lg border border-[var(--color-border)] bg-white">
          <table className="min-w-full text-left text-sm">
            <thead className="bg-slate-50 text-xs uppercase text-[var(--color-muted)]">
              <tr>
                <th className="px-4 py-3">Name</th>
                <th className="px-4 py-3">Slug</th>
                <th className="px-4 py-3" />
              </tr>
            </thead>
            <tbody className="divide-y divide-[var(--color-border)]">
              {tags.map((t) => (
                <tr key={t.id}>
                  <td className="px-4 py-3 font-medium">{t.name}</td>
                  <td className="px-4 py-3 text-[var(--color-muted)]">{t.slug}</td>
                  <td className="px-4 py-3 text-right">
                    <Button variant="secondary" onClick={() => setEditing(t)}>
                      Edit
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
            <h2 className="mb-4 text-lg font-semibold">Edit tag</h2>
            <div className="mb-3">
              <Label>Name</Label>
              <Input
                value={editing.name}
                onChange={(e) => setEditing({ ...editing, name: e.target.value })}
                required
              />
            </div>
            <div className="mb-4">
              <Label>Slug</Label>
              <Input
                value={editing.slug}
                onChange={(e) => setEditing({ ...editing, slug: e.target.value })}
              />
            </div>
            <div className="flex justify-end gap-2">
              <Button type="button" variant="secondary" onClick={() => setEditing(null)}>
                Cancel
              </Button>
              <Button type="submit" disabled={update.isPending}>
                Save
              </Button>
            </div>
          </form>
        </div>
      ) : null}
    </div>
  )
}

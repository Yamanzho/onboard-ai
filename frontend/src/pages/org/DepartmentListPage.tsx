import { useState, type FormEvent } from 'react'
import {
  EmptyState,
  ErrorAlert,
  LoadingBlock,
  PageHeader,
} from '../../components/common/PageHeader'
import { Button } from '../../components/ui/Button'
import { Input, Label, Select } from '../../components/ui/Field'
import { useDepartmentMutations, useDepartments } from '../../hooks/useDepartments'
import { t } from '../../i18n'
import { ApiError } from '../../services/apiClient'
import type { Department } from '../../types/department'

export function DepartmentListPage() {
  const { data, isLoading, error } = useDepartments()
  const { create, update } = useDepartmentMutations()
  const [name, setName] = useState('')
  const [slug, setSlug] = useState('')
  const [description, setDescription] = useState('')
  const [formError, setFormError] = useState<string | null>(null)
  const [editing, setEditing] = useState<Department | null>(null)

  const departments = data ?? []

  async function onCreate(e: FormEvent) {
    e.preventDefault()
    setFormError(null)
    try {
      await create.mutateAsync({
        name: name.trim(),
        slug: slug.trim() || null,
        description: description.trim() || null,
      })
      setName('')
      setSlug('')
      setDescription('')
    } catch (err) {
      setFormError(
        err instanceof ApiError ? err.message : t('org.departments.createFailed'),
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
          description: editing.description,
          is_active: editing.is_active,
        },
      })
      setEditing(null)
    } catch (err) {
      setFormError(
        err instanceof ApiError ? err.message : t('org.departments.updateFailed'),
      )
    }
  }

  return (
    <div>
      <PageHeader
        title={t('org.departments.title')}
        description={t('org.departments.description')}
      />
      {formError ? <ErrorAlert message={formError} /> : null}
      {error ? <ErrorAlert message={(error as Error).message} /> : null}

      <form
        onSubmit={onCreate}
        className="mb-6 grid gap-3 rounded-lg border border-[var(--color-border)] bg-white p-4 md:grid-cols-4"
      >
        <div>
          <Label htmlFor="dept-name">{t('common.name')}</Label>
          <Input
            id="dept-name"
            value={name}
            onChange={(e) => setName(e.target.value)}
            required
          />
        </div>
        <div>
          <Label htmlFor="dept-slug">{t('org.slugOptional')}</Label>
          <Input
            id="dept-slug"
            value={slug}
            onChange={(e) => setSlug(e.target.value)}
            placeholder={t('org.slugPlaceholder')}
          />
        </div>
        <div>
          <Label htmlFor="dept-desc">{t('org.description')}</Label>
          <Input
            id="dept-desc"
            value={description}
            onChange={(e) => setDescription(e.target.value)}
          />
        </div>
        <div className="flex items-end">
          <Button type="submit" disabled={create.isPending} className="w-full">
            {create.isPending ? t('common.creating') : t('org.departments.create')}
          </Button>
        </div>
      </form>

      {isLoading ? (
        <LoadingBlock />
      ) : departments.length === 0 ? (
        <EmptyState
          title={t('org.departments.emptyTitle')}
          description={t('org.departments.emptyDescription')}
        />
      ) : (
        <div className="overflow-hidden rounded-lg border border-[var(--color-border)] bg-white">
          <table className="min-w-full text-left text-sm">
            <thead className="bg-slate-50 text-xs uppercase text-[var(--color-muted)]">
              <tr>
                <th className="px-4 py-3">{t('common.name')}</th>
                <th className="px-4 py-3">{t('org.slug')}</th>
                <th className="px-4 py-3">{t('common.status')}</th>
                <th className="px-4 py-3" />
              </tr>
            </thead>
            <tbody className="divide-y divide-[var(--color-border)]">
              {departments.map((department) => (
                <tr key={department.id}>
                  <td className="px-4 py-3 font-medium">{department.name}</td>
                  <td className="px-4 py-3 text-[var(--color-muted)]">
                    {department.slug}
                  </td>
                  <td className="px-4 py-3">
                    {department.is_active ? t('org.active') : t('org.inactive')}
                  </td>
                  <td className="px-4 py-3 text-right">
                    <Button
                      variant="secondary"
                      onClick={() => setEditing(department)}
                    >
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
        <form
          onSubmit={onSaveEdit}
          className="mt-6 space-y-3 rounded-lg border border-[var(--color-border)] bg-white p-4"
        >
          <h2 className="text-sm font-semibold">
            {t('org.departments.editTitle', { name: editing.name })}
          </h2>
          <div>
            <Label htmlFor="edit-dept-name">{t('common.name')}</Label>
            <Input
              id="edit-dept-name"
              value={editing.name}
              onChange={(e) => setEditing({ ...editing, name: e.target.value })}
              required
            />
          </div>
          <div>
            <Label htmlFor="edit-dept-slug">{t('org.slug')}</Label>
            <Input
              id="edit-dept-slug"
              value={editing.slug}
              onChange={(e) => setEditing({ ...editing, slug: e.target.value })}
            />
          </div>
          <div>
            <Label htmlFor="edit-dept-desc">{t('org.description')}</Label>
            <Input
              id="edit-dept-desc"
              value={editing.description ?? ''}
              onChange={(e) =>
                setEditing({ ...editing, description: e.target.value || null })
              }
            />
          </div>
          <div>
            <Label htmlFor="edit-dept-active">{t('common.status')}</Label>
            <Select
              id="edit-dept-active"
              value={editing.is_active ? 'active' : 'inactive'}
              onChange={(e) =>
                setEditing({ ...editing, is_active: e.target.value === 'active' })
              }
            >
              <option value="active">{t('org.active')}</option>
              <option value="inactive">{t('org.inactive')}</option>
            </Select>
          </div>
          <div className="flex gap-2">
            <Button type="submit" disabled={update.isPending}>
              {update.isPending ? t('common.saving') : t('common.save')}
            </Button>
            <Button
              type="button"
              variant="secondary"
              onClick={() => setEditing(null)}
            >
              {t('common.cancel')}
            </Button>
          </div>
        </form>
      ) : null}
    </div>
  )
}

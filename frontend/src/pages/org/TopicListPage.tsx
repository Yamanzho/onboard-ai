import { useMemo, useState, type FormEvent } from 'react'
import {
  EmptyState,
  ErrorAlert,
  LoadingBlock,
  PageHeader,
} from '../../components/common/PageHeader'
import { Button } from '../../components/ui/Button'
import { Input, Label, Select } from '../../components/ui/Field'
import { useDepartments } from '../../hooks/useDepartments'
import { useEmployees } from '../../hooks/useEmployees'
import { useTopicMutations, useTopics } from '../../hooks/useTopics'
import { t } from '../../i18n'
import { ApiError } from '../../services/apiClient'
import type { QuestionTopic } from '../../types/topic'

export function TopicListPage() {
  const { data, isLoading, error } = useTopics()
  const { data: departments = [] } = useDepartments()
  const { data: employees = [] } = useEmployees()
  const { create, update, setResponsibility } = useTopicMutations()
  const [name, setName] = useState('')
  const [slug, setSlug] = useState('')
  const [description, setDescription] = useState('')
  const [departmentId, setDepartmentId] = useState('')
  const [employeeId, setEmployeeId] = useState('')
  const [formError, setFormError] = useState<string | null>(null)
  const [editing, setEditing] = useState<QuestionTopic | null>(null)

  const topics = data ?? []
  const activeDepartments = useMemo(
    () => departments.filter((item) => item.is_active),
    [departments],
  )
  const activeEmployees = useMemo(
    () => employees.filter((item) => item.status === 'active'),
    [employees],
  )

  async function onCreate(e: FormEvent) {
    e.preventDefault()
    setFormError(null)
    try {
      await create.mutateAsync({
        name: name.trim(),
        slug: slug.trim() || null,
        description: description.trim() || null,
        department_id: departmentId || null,
        employee_id: employeeId || null,
      })
      setName('')
      setSlug('')
      setDescription('')
      setDepartmentId('')
      setEmployeeId('')
    } catch (err) {
      setFormError(err instanceof ApiError ? err.message : t('org.topics.createFailed'))
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
      const nextDepartment = editing.responsibility?.department_id ?? ''
      const nextEmployee = editing.responsibility?.employee_id ?? ''
      if (nextDepartment || nextEmployee) {
        await setResponsibility.mutateAsync({
          id: editing.id,
          payload: {
            department_id: nextDepartment || null,
            employee_id: nextEmployee || null,
          },
        })
      }
      setEditing(null)
    } catch (err) {
      setFormError(err instanceof ApiError ? err.message : t('org.topics.updateFailed'))
    }
  }

  return (
    <div>
      <PageHeader
        title={t('org.topics.title')}
        description={t('org.topics.description')}
      />
      {formError ? <ErrorAlert message={formError} /> : null}
      {error ? <ErrorAlert message={(error as Error).message} /> : null}

      <form
        onSubmit={onCreate}
        className="mb-6 grid gap-3 rounded-lg border border-[var(--color-border)] bg-white p-4 md:grid-cols-3"
      >
        <div>
          <Label htmlFor="topic-name">{t('common.name')}</Label>
          <Input
            id="topic-name"
            value={name}
            onChange={(e) => setName(e.target.value)}
            required
          />
        </div>
        <div>
          <Label htmlFor="topic-slug">{t('org.slugOptional')}</Label>
          <Input
            id="topic-slug"
            value={slug}
            onChange={(e) => setSlug(e.target.value)}
            placeholder={t('org.slugPlaceholder')}
          />
        </div>
        <div>
          <Label htmlFor="topic-desc">{t('org.description')}</Label>
          <Input
            id="topic-desc"
            value={description}
            onChange={(e) => setDescription(e.target.value)}
          />
        </div>
        <div>
          <Label htmlFor="topic-dept">{t('org.responsibleDepartment')}</Label>
          <Select
            id="topic-dept"
            value={departmentId}
            onChange={(e) => setDepartmentId(e.target.value)}
          >
            <option value="">{t('org.none')}</option>
            {activeDepartments.map((item) => (
              <option key={item.id} value={item.id}>
                {item.name}
              </option>
            ))}
          </Select>
        </div>
        <div>
          <Label htmlFor="topic-emp">{t('org.responsibleEmployee')}</Label>
          <Select
            id="topic-emp"
            value={employeeId}
            onChange={(e) => setEmployeeId(e.target.value)}
          >
            <option value="">{t('org.none')}</option>
            {activeEmployees.map((item) => (
              <option key={item.id} value={item.id}>
                {item.full_name}
              </option>
            ))}
          </Select>
        </div>
        <div className="flex items-end">
          <Button type="submit" disabled={create.isPending} className="w-full">
            {create.isPending ? t('common.creating') : t('org.topics.create')}
          </Button>
        </div>
      </form>

      {isLoading ? (
        <LoadingBlock />
      ) : topics.length === 0 ? (
        <EmptyState
          title={t('org.topics.emptyTitle')}
          description={t('org.topics.emptyDescription')}
        />
      ) : (
        <div className="overflow-hidden rounded-lg border border-[var(--color-border)] bg-white">
          <table className="min-w-full text-left text-sm">
            <thead className="bg-slate-50 text-xs uppercase text-[var(--color-muted)]">
              <tr>
                <th className="px-4 py-3">{t('common.name')}</th>
                <th className="px-4 py-3">{t('org.slug')}</th>
                <th className="px-4 py-3">{t('org.responsibleDepartment')}</th>
                <th className="px-4 py-3">{t('org.responsibleEmployee')}</th>
                <th className="px-4 py-3">{t('common.status')}</th>
                <th className="px-4 py-3" />
              </tr>
            </thead>
            <tbody className="divide-y divide-[var(--color-border)]">
              {topics.map((topic) => (
                <tr key={topic.id}>
                  <td className="px-4 py-3 font-medium">{topic.name}</td>
                  <td className="px-4 py-3 text-[var(--color-muted)]">{topic.slug}</td>
                  <td className="px-4 py-3">
                    {topic.responsibility?.department?.name ?? t('common.emDash')}
                  </td>
                  <td className="px-4 py-3">
                    {topic.responsibility?.employee?.full_name ?? t('common.emDash')}
                  </td>
                  <td className="px-4 py-3">
                    {topic.is_active ? t('org.active') : t('org.inactive')}
                  </td>
                  <td className="px-4 py-3 text-right">
                    <Button variant="secondary" onClick={() => setEditing(topic)}>
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
            {t('org.topics.editTitle', { name: editing.name })}
          </h2>
          <div>
            <Label htmlFor="edit-topic-name">{t('common.name')}</Label>
            <Input
              id="edit-topic-name"
              value={editing.name}
              onChange={(e) => setEditing({ ...editing, name: e.target.value })}
              required
            />
          </div>
          <div>
            <Label htmlFor="edit-topic-slug">{t('org.slug')}</Label>
            <Input
              id="edit-topic-slug"
              value={editing.slug}
              onChange={(e) => setEditing({ ...editing, slug: e.target.value })}
            />
          </div>
          <div>
            <Label htmlFor="edit-topic-dept">{t('org.responsibleDepartment')}</Label>
            <Select
              id="edit-topic-dept"
              value={editing.responsibility?.department_id ?? ''}
              onChange={(e) =>
                setEditing({
                  ...editing,
                  responsibility: {
                    id: editing.responsibility?.id ?? editing.id,
                    topic_id: editing.id,
                    department_id: e.target.value || null,
                    employee_id: editing.responsibility?.employee_id ?? null,
                    department: editing.responsibility?.department ?? null,
                    employee: editing.responsibility?.employee ?? null,
                    created_at: editing.responsibility?.created_at ?? editing.created_at,
                    updated_at: editing.responsibility?.updated_at ?? editing.updated_at,
                  },
                })
              }
            >
              <option value="">{t('org.none')}</option>
              {departments.map((item) => (
                <option key={item.id} value={item.id}>
                  {item.name}
                </option>
              ))}
            </Select>
          </div>
          <div>
            <Label htmlFor="edit-topic-emp">{t('org.responsibleEmployee')}</Label>
            <Select
              id="edit-topic-emp"
              value={editing.responsibility?.employee_id ?? ''}
              onChange={(e) =>
                setEditing({
                  ...editing,
                  responsibility: {
                    id: editing.responsibility?.id ?? editing.id,
                    topic_id: editing.id,
                    department_id: editing.responsibility?.department_id ?? null,
                    employee_id: e.target.value || null,
                    department: editing.responsibility?.department ?? null,
                    employee: editing.responsibility?.employee ?? null,
                    created_at: editing.responsibility?.created_at ?? editing.created_at,
                    updated_at: editing.responsibility?.updated_at ?? editing.updated_at,
                  },
                })
              }
            >
              <option value="">{t('org.none')}</option>
              {activeEmployees.map((item) => (
                <option key={item.id} value={item.id}>
                  {item.full_name}
                </option>
              ))}
            </Select>
          </div>
          <div>
            <Label htmlFor="edit-topic-active">{t('common.status')}</Label>
            <Select
              id="edit-topic-active"
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
            <Button
              type="submit"
              disabled={update.isPending || setResponsibility.isPending}
            >
              {update.isPending || setResponsibility.isPending
                ? t('common.saving')
                : t('common.save')}
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

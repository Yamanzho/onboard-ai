import { useMemo, useState, type FormEvent } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { ErrorAlert, PageHeader } from '../../components/common/PageHeader'
import { Button } from '../../components/ui/Button'
import { Input, Label, Select } from '../../components/ui/Field'
import { useAssignmentMutations } from '../../hooks/useAssignments'
import { useArticles } from '../../hooks/useArticles'
import { useDepartments } from '../../hooks/useDepartments'
import { useEmployees } from '../../hooks/useEmployees'
import { usePrograms } from '../../hooks/usePrograms'
import { useWorkspacePaths } from '../../hooks/useWorkspacePaths'
import { labelAssignmentPriority, labelAssignmentType, t } from '../../i18n'
import { ApiError } from '../../services/apiClient'
import type { Article } from '../../types/article'
import {
  ASSIGNMENT_PRIORITIES,
  ASSIGNMENT_TYPES,
  type AcknowledgementDocumentInput,
  type AssignmentCreate,
  type AssignmentPriority,
  type AssignmentType,
} from '../../types/assignment'

function toggleId(current: string[], id: string): string[] {
  return current.includes(id) ? current.filter((item) => item !== id) : [...current, id]
}

function toIso(value: string): string | null {
  if (!value) return null
  const parsed = new Date(value)
  if (Number.isNaN(parsed.getTime())) return null
  return parsed.toISOString()
}

export function AssignmentCreatePage() {
  const navigate = useNavigate()
  const paths = useWorkspacePaths()
  const { data: employees = [], isLoading: employeesLoading } = useEmployees()
  const { data: departments = [], isLoading: departmentsLoading } = useDepartments(true)
  const { data: programs = [], isLoading: programsLoading } = usePrograms({
    is_active: true,
  })
  const { data: articlesPage, isLoading: articlesLoading } = useArticles({
    status: 'published',
    limit: 200,
  })
  const { create } = useAssignmentMutations()

  const [assignmentType, setAssignmentType] = useState<AssignmentType>('program')
  const [employeeIds, setEmployeeIds] = useState<string[]>([])
  const [departmentIds, setDepartmentIds] = useState<string[]>([])
  const [programId, setProgramId] = useState('')
  const [documents, setDocuments] = useState<AcknowledgementDocumentInput[]>([])
  const [priority, setPriority] = useState<AssignmentPriority>('normal')
  const [dueAt, setDueAt] = useState('')
  const [overrides, setOverrides] = useState<Record<string, string>>({})
  const [error, setError] = useState<string | null>(null)

  const assignableEmployees = useMemo(
    () => employees.filter((e) => e.status !== 'archived'),
    [employees],
  )
  const activeDepartments = useMemo(
    () => departments.filter((d) => d.is_active),
    [departments],
  )

  const resolvedRecipients = useMemo(() => {
    const byId = new Map<string, (typeof assignableEmployees)[number]>()
    for (const employee of assignableEmployees) {
      if (
        employee.department_id &&
        departmentIds.includes(employee.department_id)
      ) {
        byId.set(employee.id, employee)
      }
    }
    for (const id of employeeIds) {
      const employee = assignableEmployees.find((e) => e.id === id)
      if (employee) byId.set(employee.id, employee)
    }
    return [...byId.values()]
  }, [assignableEmployees, departmentIds, employeeIds])

  async function onSubmit(e: FormEvent) {
    e.preventDefault()
    setError(null)

    if (employeeIds.length === 0 && departmentIds.length === 0) {
      setError(t('assignments.selectEmployee'))
      return
    }
    if (assignmentType === 'program' && !programId) {
      setError(t('assignments.selectProgram'))
      return
    }
    if (assignmentType === 'acknowledgement' && documents.length === 0) {
      setError(t('assignments.selectDocuments'))
      return
    }

    const deadlineOverrides: Record<string, string> = {}
    for (const recipient of resolvedRecipients) {
      const override = overrides[recipient.id]
      const iso = override ? toIso(override) : null
      if (iso) deadlineOverrides[recipient.id] = iso
    }

    const payload: AssignmentCreate = {
      assignment_type: assignmentType,
      priority,
      due_at: toIso(dueAt),
      deadline_overrides:
        Object.keys(deadlineOverrides).length > 0 ? deadlineOverrides : undefined,
    }
    if (assignmentType === 'program') {
      payload.program_id = programId
    } else {
      payload.documents = documents.map((item, index) => ({
        ...item,
        position: index + 1,
      }))
    }
    if (departmentIds.length === 0 && employeeIds.length === 1) {
      payload.employee_id = employeeIds[0]
    } else {
      payload.employee_ids = employeeIds
      payload.department_ids = departmentIds
    }

    try {
      await create.mutateAsync(payload)
      navigate(paths.assignments)
    } catch (err) {
      setError(
        err instanceof ApiError ? err.message : t('assignments.createFailed'),
      )
    }
  }

  return (
    <div>
      <PageHeader
        title={t('assignments.createTitle')}
        description={t('assignments.createDescription')}
        action={
          <Link to={paths.assignments}>
            <Button variant="secondary">{t('assignments.backToList')}</Button>
          </Link>
        }
      />

      {error ? <ErrorAlert message={error} /> : null}

      <form
        onSubmit={onSubmit}
        className="max-w-xl space-y-4 rounded-lg border border-[var(--color-border)] bg-white p-5"
        noValidate
      >
        <div>
          <Label htmlFor="assignment-type">{t('assignments.assignmentType')}</Label>
          <Select
            id="assignment-type"
            value={assignmentType}
            onChange={(e) => setAssignmentType(e.target.value as AssignmentType)}
          >
            {ASSIGNMENT_TYPES.map((value) => (
              <option key={value} value={value}>
                {labelAssignmentType(value)}
              </option>
            ))}
          </Select>
        </div>

        {assignmentType === 'program' ? (
          <div>
            <Label htmlFor="assignment-program">{t('assignments.program')}</Label>
            <Select
              id="assignment-program"
              value={programId}
              onChange={(e) => setProgramId(e.target.value)}
              required
              disabled={programsLoading}
            >
              <option value="">{t('assignments.selectProgramPlaceholder')}</option>
              {programs.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.title}
                </option>
              ))}
            </Select>
            {programs.length === 0 && !programsLoading ? (
              <p className="mt-1 text-xs text-[var(--color-muted)]">
                {t('assignments.noPublishedPrograms')}
              </p>
            ) : null}
          </div>
        ) : (
          <AcknowledgementDocumentPicker
            articles={(articlesPage?.items ?? []).filter(
              (article) => article.status === 'published',
            )}
            loading={articlesLoading}
            documents={documents}
            onChange={setDocuments}
          />
        )}

        <div>
          <Label>{t('assignments.departments')}</Label>
          <div className="max-h-40 space-y-1 overflow-y-auto rounded-md border border-[var(--color-border)] p-2">
            {departmentsLoading ? (
              <p className="text-xs text-[var(--color-muted)]">{t('common.loading')}</p>
            ) : activeDepartments.length === 0 ? (
              <p className="text-xs text-[var(--color-muted)]">
                {t('assignments.noActiveDepartments')}
              </p>
            ) : (
              activeDepartments.map((dept) => (
                <label key={dept.id} className="flex items-center gap-2 text-sm">
                  <input
                    type="checkbox"
                    checked={departmentIds.includes(dept.id)}
                    onChange={() => setDepartmentIds((ids) => toggleId(ids, dept.id))}
                  />
                  {dept.name}
                </label>
              ))
            )}
          </div>
        </div>

        <div>
          <Label>{t('assignments.employees')}</Label>
          <div className="max-h-48 space-y-1 overflow-y-auto rounded-md border border-[var(--color-border)] p-2">
            {employeesLoading ? (
              <p className="text-xs text-[var(--color-muted)]">{t('common.loading')}</p>
            ) : (
              assignableEmployees.map((e) => (
                <label key={e.id} className="flex items-center gap-2 text-sm">
                  <input
                    type="checkbox"
                    checked={employeeIds.includes(e.id)}
                    onChange={() => setEmployeeIds((ids) => toggleId(ids, e.id))}
                  />
                  {e.full_name}
                  {e.email ? ` (${e.email})` : ''}
                </label>
              ))
            )}
          </div>
        </div>

        <p className="text-sm text-[var(--color-muted)]">
          {t('assignments.recipientCount', { count: resolvedRecipients.length })}
        </p>

        <div>
          <Label htmlFor="assignment-priority">{t('assignments.priority')}</Label>
          <Select
            id="assignment-priority"
            value={priority}
            onChange={(e) => setPriority(e.target.value as AssignmentPriority)}
          >
            {ASSIGNMENT_PRIORITIES.map((value) => (
              <option key={value} value={value}>
                {labelAssignmentPriority(value)}
              </option>
            ))}
          </Select>
        </div>

        <div>
          <Label htmlFor="assignment-due">{t('assignments.defaultDueDate')}</Label>
          <Input
            id="assignment-due"
            type="datetime-local"
            value={dueAt}
            onChange={(e) => setDueAt(e.target.value)}
          />
        </div>

        {resolvedRecipients.length > 0 ? (
          <details className="rounded-md border border-[var(--color-border)] p-3">
            <summary className="cursor-pointer text-sm font-medium">
              {t('assignments.overridesTitle')}
            </summary>
            <p className="mt-1 text-xs text-[var(--color-muted)]">
              {t('assignments.overridesHint')}
            </p>
            <div className="mt-3 space-y-2">
              {resolvedRecipients.map((employee) => (
                <div key={employee.id} className="grid gap-1 sm:grid-cols-[1fr_12rem]">
                  <Label htmlFor={`override-${employee.id}`}>{employee.full_name}</Label>
                  <Input
                    id={`override-${employee.id}`}
                    type="datetime-local"
                    value={overrides[employee.id] ?? ''}
                    onChange={(e) =>
                      setOverrides((current) => ({
                        ...current,
                        [employee.id]: e.target.value,
                      }))
                    }
                  />
                </div>
              ))}
            </div>
          </details>
        ) : null}

        <Button type="submit" disabled={create.isPending}>
          {create.isPending ? t('assignments.assigning') : t('assignments.create')}
        </Button>
      </form>
    </div>
  )
}

function articleTitle(article: Article): string {
  return article.current_version?.title ?? t('knowledge.articles.untitled')
}

function AcknowledgementDocumentPicker({
  articles,
  loading,
  documents,
  onChange,
}: {
  articles: Article[]
  loading: boolean
  documents: AcknowledgementDocumentInput[]
  onChange: (next: AcknowledgementDocumentInput[]) => void
}) {
  const selected = new Set(documents.map((item) => item.article_id))

  function add(articleId: string) {
    if (selected.has(articleId)) return
    onChange([
      ...documents,
      { article_id: articleId, position: documents.length + 1, is_required: true },
    ])
  }

  function remove(articleId: string) {
    onChange(
      documents
        .filter((item) => item.article_id !== articleId)
        .map((item, index) => ({ ...item, position: index + 1 })),
    )
  }

  function move(articleId: string, delta: number) {
    const index = documents.findIndex((item) => item.article_id === articleId)
    const nextIndex = index + delta
    if (index < 0 || nextIndex < 0 || nextIndex >= documents.length) return
    const next = [...documents]
    const [row] = next.splice(index, 1)
    next.splice(nextIndex, 0, row)
    onChange(next.map((item, i) => ({ ...item, position: i + 1 })))
  }

  function toggleRequired(articleId: string) {
    onChange(
      documents.map((item) =>
        item.article_id === articleId
          ? { ...item, is_required: !item.is_required }
          : item,
      ),
    )
  }

  return (
    <div className="space-y-3">
      <p className="text-xs text-[var(--color-muted)]">
        {t('assignments.acknowledgementHint')}
      </p>
      <div>
        <Label>{t('assignments.documents')}</Label>
        <div className="max-h-40 space-y-1 overflow-y-auto rounded-md border border-[var(--color-border)] p-2">
          {loading ? (
            <p className="text-xs text-[var(--color-muted)]">{t('common.loading')}</p>
          ) : articles.length === 0 ? (
            <p className="text-xs text-[var(--color-muted)]">
              {t('assignments.noPublishedArticles')}
            </p>
          ) : (
            articles.map((article) => (
              <label key={article.id} className="flex items-center gap-2 text-sm">
                <input
                  type="checkbox"
                  checked={selected.has(article.id)}
                  onChange={() =>
                    selected.has(article.id) ? remove(article.id) : add(article.id)
                  }
                />
                {articleTitle(article)}
                {article.current_version ? ` · v${article.current_version.version}` : ''}
              </label>
            ))
          )}
        </div>
      </div>
      {documents.length > 0 ? (
        <div>
          <Label>{t('assignments.selectedDocuments')}</Label>
          <ol className="mt-2 space-y-2">
            {documents.map((item, index) => {
              const article = articles.find((row) => row.id === item.article_id)
              return (
                <li
                  key={item.article_id}
                  className="flex flex-wrap items-center gap-2 rounded-md border border-[var(--color-border)] px-3 py-2 text-sm"
                >
                  <span className="text-[var(--color-muted)]">{index + 1}.</span>
                  <span className="min-w-0 flex-1 font-medium">
                    {article ? articleTitle(article) : item.article_id.slice(0, 8)}
                  </span>
                  <label className="flex items-center gap-1 text-xs">
                    <input
                      type="checkbox"
                      checked={item.is_required}
                      onChange={() => toggleRequired(item.article_id)}
                    />
                    {item.is_required
                      ? t('assignments.documentRequired')
                      : t('assignments.documentOptional')}
                  </label>
                  <Button
                    type="button"
                    variant="secondary"
                    disabled={index === 0}
                    onClick={() => move(item.article_id, -1)}
                  >
                    {t('assignments.moveUp')}
                  </Button>
                  <Button
                    type="button"
                    variant="secondary"
                    disabled={index === documents.length - 1}
                    onClick={() => move(item.article_id, 1)}
                  >
                    {t('assignments.moveDown')}
                  </Button>
                </li>
              )
            })}
          </ol>
        </div>
      ) : null}
    </div>
  )
}

import { useMemo, useState, type FormEvent } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { ErrorAlert, PageHeader } from '../../components/common/PageHeader'
import { Button } from '../../components/ui/Button'
import { Input, Label, Select } from '../../components/ui/Field'
import { useAssignmentMutations } from '../../hooks/useAssignments'
import { useEmployees } from '../../hooks/useEmployees'
import { usePrograms } from '../../hooks/usePrograms'
import { t } from '../../i18n'
import { ApiError } from '../../services/apiClient'

export function AssignmentCreatePage() {
  const navigate = useNavigate()
  const { data: employees = [], isLoading: employeesLoading } = useEmployees()
  const { data: programs = [], isLoading: programsLoading } = usePrograms({
    is_active: true,
  })
  const { create } = useAssignmentMutations()

  const [employeeId, setEmployeeId] = useState('')
  const [programId, setProgramId] = useState('')
  const [dueAt, setDueAt] = useState('')
  const [error, setError] = useState<string | null>(null)

  const assignableEmployees = useMemo(
    () => employees.filter((e) => e.status !== 'archived'),
    [employees],
  )

  async function onSubmit(e: FormEvent) {
    e.preventDefault()
    setError(null)

    if (!employeeId) {
      setError(t('assignments.selectEmployee'))
      return
    }
    if (!programId) {
      setError(t('assignments.selectProgram'))
      return
    }

    try {
      await create.mutateAsync({
        employee_id: employeeId,
        program_id: programId,
        due_at: dueAt ? new Date(dueAt).toISOString() : null,
      })
      navigate('/assignments')
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
          <Link to="/assignments">
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
          <Label htmlFor="assignment-employee">{t('assignments.employee')}</Label>
          <Select
            id="assignment-employee"
            value={employeeId}
            onChange={(e) => setEmployeeId(e.target.value)}
            required
            disabled={employeesLoading}
          >
            <option value="">{t('assignments.selectEmployeePlaceholder')}</option>
            {assignableEmployees.map((e) => (
              <option key={e.id} value={e.id}>
                {e.full_name}
                {e.email ? ` (${e.email})` : ''}
              </option>
            ))}
          </Select>
        </div>

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

        <div>
          <Label htmlFor="assignment-due">{t('assignments.dueDate')}</Label>
          <Input
            id="assignment-due"
            type="datetime-local"
            value={dueAt}
            onChange={(e) => setDueAt(e.target.value)}
          />
        </div>

        <Button type="submit" disabled={create.isPending}>
          {create.isPending ? t('assignments.assigning') : t('assignments.create')}
        </Button>
      </form>
    </div>
  )
}

import { useNavigate } from 'react-router-dom'
import { ErrorAlert, PageHeader } from '../../components/common/PageHeader'
import {
  ProgramForm,
  type ProgramFormValues,
} from '../../components/onboarding/ProgramForm'
import { useProgramMutations } from '../../hooks/usePrograms'
import { useWorkspacePaths } from '../../hooks/useWorkspacePaths'
import { t } from '../../i18n'
import { ApiError } from '../../services/apiClient'

export function ProgramCreatePage() {
  const navigate = useNavigate()
  const paths = useWorkspacePaths()
  const { create } = useProgramMutations()

  async function onSubmit(values: ProgramFormValues) {
    try {
      const program = await create.mutateAsync({
        title: values.title,
        description: values.description || null,
      })
      navigate(paths.programEdit(program.id))
    } catch (err) {
      throw new Error(
        err instanceof ApiError ? err.message : t('programs.createFailed'),
      )
    }
  }

  return (
    <div>
      <PageHeader
        title={t('programs.createTitle')}
        description={t('programs.createDescription')}
      />
      {create.isError ? (
        <ErrorAlert
          message={
            create.error instanceof Error
              ? create.error.message
              : t('common.createFailed')
          }
        />
      ) : null}
      <div className="rounded-lg border border-[var(--color-border)] bg-white p-5">
        <ProgramForm
          initial={{ title: '', description: '' }}
          submitLabel={t('programs.create')}
          pending={create.isPending}
          onSubmit={onSubmit}
        />
      </div>
    </div>
  )
}

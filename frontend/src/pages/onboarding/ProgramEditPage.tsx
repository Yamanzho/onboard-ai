import { Link, useParams } from 'react-router-dom'
import { useState } from 'react'
import {
  ErrorAlert,
  LoadingBlock,
  PageHeader,
} from '../../components/common/PageHeader'
import {
  ProgramForm,
  type ProgramFormValues,
} from '../../components/onboarding/ProgramForm'
import { ProgramStatusBadge } from '../../components/onboarding/ProgramStatusBadge'
import { ProgramStepsEditor } from '../../components/onboarding/ProgramStepsEditor'
import {
  ProgramLockBadge,
  ProgramLockBanner,
  ProgramRevisionBadge,
} from '../../components/onboarding/ProgramRevisionBadge'
import { Button } from '../../components/ui/Button'
import {
  useProgram,
  useProgramMutations,
} from '../../hooks/usePrograms'
import { useWorkspacePaths } from '../../hooks/useWorkspacePaths'
import { t } from '../../i18n'
import { ApiError } from '../../services/apiClient'

export function ProgramEditPage() {
  const { programId } = useParams<{ programId: string }>()
  const paths = useWorkspacePaths()
  const { data: program, isLoading, error } = useProgram(programId)
  const { update, publish, archive } = useProgramMutations()
  const [actionError, setActionError] = useState<string | null>(null)

  async function onSubmit(values: ProgramFormValues) {
    if (!programId) return
    try {
      await update.mutateAsync({
        id: programId,
        payload: {
          title: values.title,
          description: values.description || null,
        },
      })
    } catch (err) {
      throw new Error(
        err instanceof ApiError ? err.message : t('programs.updateFailed'),
      )
    }
  }

  async function onPublish() {
    if (!program) return
    const ok = window.confirm(
      t('programs.publishConfirm', { title: program.title }),
    )
    if (!ok) return
    setActionError(null)
    try {
      await publish.mutateAsync(program.id)
    } catch (err) {
      setActionError(
        err instanceof ApiError ? err.message : t('programs.publishFailed'),
      )
    }
  }

  async function onArchive() {
    if (!program) return
    const ok = window.confirm(
      t('programs.archiveConfirmShort', { title: program.title }),
    )
    if (!ok) return
    setActionError(null)
    try {
      await archive.mutateAsync(program.id)
    } catch (err) {
      setActionError(
        err instanceof ApiError ? err.message : t('programs.archiveFailed'),
      )
    }
  }

  if (isLoading) return <LoadingBlock />
  if (error || !program || !programId) {
    return (
      <ErrorAlert
        message={
          error instanceof Error ? error.message : t('programs.notFound')
        }
      />
    )
  }

  return (
    <div>
      <PageHeader
        title={t('programs.editTitle', { title: program.title })}
        description={t('programs.editDescription')}
        action={
          <Link to={paths.program(program.id)}>
            <Button variant="secondary">{t('employees.backToDetails')}</Button>
          </Link>
        }
      />

      {actionError ? <ErrorAlert message={actionError} /> : null}

      <div className="mb-4 flex flex-wrap items-center gap-3 rounded-lg border border-[var(--color-border)] bg-white px-4 py-3 text-sm">
        <ProgramStatusBadge program={program} />
        <ProgramRevisionBadge revision={program.revision} />
        <ProgramLockBadge program={program} />
        <span className="text-[var(--color-muted)]">
          {t('common.id')}: {program.id}
        </span>
        <div className="ml-auto flex gap-2">
          {!program.is_active ? (
            <Button
              variant="secondary"
              disabled={publish.isPending}
              onClick={() => void onPublish()}
            >
              {t('common.publish')}
            </Button>
          ) : (
            <Button
              variant="ghost"
              disabled={archive.isPending}
              onClick={() => void onArchive()}
            >
              {t('common.archive')}
            </Button>
          )}
        </div>
      </div>

      <div className="mb-4">
        <ProgramLockBanner program={program} />
      </div>

      <div className="mb-6 rounded-lg border border-[var(--color-border)] bg-white p-5">
        <ProgramForm
          key={`${program.id}-${program.updated_at}`}
          initial={{
            title: program.title,
            description: program.description ?? '',
          }}
          submitLabel={t('programs.saveProgram')}
          pending={update.isPending}
          onSubmit={onSubmit}
        />
      </div>

      <ProgramStepsEditor
        programId={programId}
        structureLocked={program.structure_locked === true}
      />
    </div>
  )
}

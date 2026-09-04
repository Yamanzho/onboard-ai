import { Link, useParams } from 'react-router-dom'
import { useState } from 'react'
import {
  ErrorAlert,
  LoadingBlock,
  PageHeader,
} from '../../components/common/PageHeader'
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

function formatDate(value: string) {
  try {
    return new Date(value).toLocaleString()
  } catch {
    return value
  }
}

export function ProgramDetailPage() {
  const { programId } = useParams<{ programId: string }>()
  const paths = useWorkspacePaths()
  const { data: program, isLoading, error } = useProgram(programId)
  const { publish, archive } = useProgramMutations()
  const [actionError, setActionError] = useState<string | null>(null)

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

  const rows: { label: string; value: string }[] = [
    { label: t('common.name'), value: program.title },
    {
      label: t('common.description'),
      value: program.description ?? t('common.emDash'),
    },
    { label: t('programs.revision'), value: `v${program.revision ?? 1}` },
    { label: t('common.created'), value: formatDate(program.created_at) },
    { label: t('common.updated'), value: formatDate(program.updated_at) },
    { label: t('programs.programId'), value: program.id },
    { label: t('settings.companyId'), value: program.company_id },
  ]

  return (
    <div>
      <PageHeader
        title={program.title}
        description={t('programs.detailDescription')}
        action={
          <div className="flex flex-wrap gap-2">
            <Link to={paths.onboarding}>
              <Button variant="secondary">{t('assignments.backToList')}</Button>
            </Link>
            <Link to={paths.programEdit(program.id)}>
              <Button>{t('common.edit')}</Button>
            </Link>
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
        }
      />

      {actionError ? <ErrorAlert message={actionError} /> : null}

      <div className="mb-4 flex flex-wrap items-center gap-3 rounded-lg border border-[var(--color-border)] bg-white px-4 py-3 text-sm">
        <ProgramStatusBadge program={program} />
        <ProgramRevisionBadge revision={program.revision} />
        <ProgramLockBadge program={program} />
      </div>
      <div className="mb-4">
        <ProgramLockBanner program={program} />
      </div>

      <div className="mb-6 overflow-hidden rounded-lg border border-[var(--color-border)] bg-white">
        <dl className="divide-y divide-[var(--color-border)]">
          {rows.map((row) => (
            <div
              key={row.label}
              className="grid gap-1 px-4 py-3 sm:grid-cols-[12rem_1fr] sm:gap-4"
            >
              <dt className="text-sm text-[var(--color-muted)]">{row.label}</dt>
              <dd className="whitespace-pre-wrap break-words text-sm font-medium">
                {row.value}
              </dd>
            </div>
          ))}
        </dl>
      </div>

      <ProgramStepsEditor programId={programId} readOnly />
    </div>
  )
}

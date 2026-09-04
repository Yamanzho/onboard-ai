import { Badge } from '../ui/Badge'
import { t } from '../../i18n'
import type { Program } from '../../types/program'

export function ProgramRevisionBadge({
  revision,
}: {
  revision: number | undefined
}) {
  return (
    <Badge>
      {t('programs.revisionBadge', { revision: revision ?? 1 })}
    </Badge>
  )
}

export function ProgramLockBadge({ program }: { program: Program }) {
  const locked = program.structure_locked === true
  return (
    <Badge tone={locked ? 'warning' : 'success'}>
      {locked ? t('programs.locked') : t('programs.unlocked')}
    </Badge>
  )
}

export function ProgramLockBanner({ program }: { program: Program }) {
  if (!program.structure_locked) return null
  return (
    <div className="rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-sm text-amber-900">
      {t('programs.lockedExplanation')}
    </div>
  )
}


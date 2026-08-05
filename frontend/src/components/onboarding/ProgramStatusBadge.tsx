import { Badge } from '../ui/Badge'
import { labelProgramStatus } from '../../i18n'
import type { Program } from '../../types/program'

export function ProgramStatusBadge({ program }: { program: Program }) {
  const label = labelProgramStatus(program.is_active)
  return (
    <Badge tone={program.is_active ? 'success' : 'warning'}>{label}</Badge>
  )
}

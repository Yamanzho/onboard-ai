import { Badge } from '../ui/Badge'
import { labelAssignmentPriority } from '../../i18n'

export function AssignmentPriorityBadge({
  priority,
}: {
  priority?: string | null
}) {
  const value = priority || 'normal'
  const tone =
    value === 'critical' ? 'danger' : value === 'important' ? 'warning' : 'neutral'
  return <Badge tone={tone}>{labelAssignmentPriority(value)}</Badge>
}

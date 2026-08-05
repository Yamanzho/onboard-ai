import { Badge } from '../ui/Badge'
import { labelAssignmentStatus } from '../../i18n'

export function AssignmentStatusBadge({ status }: { status: string }) {
  const tone =
    status === 'completed'
      ? 'success'
      : status === 'in_progress'
        ? 'warning'
        : status === 'cancelled'
          ? 'danger'
          : 'neutral'
  return <Badge tone={tone}>{labelAssignmentStatus(status)}</Badge>
}

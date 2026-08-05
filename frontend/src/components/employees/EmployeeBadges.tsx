import { Badge } from '../ui/Badge'
import { labelEmployeeRole, labelEmployeeStatus } from '../../i18n'

export function EmployeeStatusBadge({ status }: { status: string }) {
  const tone =
    status === 'active'
      ? 'success'
      : status === 'invited'
        ? 'warning'
        : status === 'archived'
          ? 'danger'
          : 'neutral'
  return <Badge tone={tone}>{labelEmployeeStatus(status)}</Badge>
}

export function EmployeeRoleBadge({ role }: { role: string }) {
  const tone =
    role === 'admin' ? 'danger' : role === 'hr' ? 'warning' : 'neutral'
  return <Badge tone={tone}>{labelEmployeeRole(role)}</Badge>
}

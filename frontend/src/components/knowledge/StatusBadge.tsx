import { Badge } from '../ui/Badge'

export function StatusBadge({ status }: { status: string }) {
  const tone =
    status === 'published'
      ? 'success'
      : status === 'draft'
        ? 'warning'
        : status === 'archived'
          ? 'danger'
          : 'neutral'
  return <Badge tone={tone}>{status}</Badge>
}

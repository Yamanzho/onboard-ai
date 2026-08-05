import { Badge } from '../ui/Badge'
import { labelArticleStatus } from '../../i18n'

export function StatusBadge({ status }: { status: string }) {
  const tone =
    status === 'published'
      ? 'success'
      : status === 'draft'
        ? 'warning'
        : status === 'archived'
          ? 'danger'
          : 'neutral'
  return <Badge tone={tone}>{labelArticleStatus(status)}</Badge>
}

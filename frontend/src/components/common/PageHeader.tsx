import type { ReactNode } from 'react'
import { Link } from 'react-router-dom'
import { t } from '../../i18n'

export function PageHeader({
  title,
  description,
  action,
}: {
  title: string
  description?: string
  action?: ReactNode
}) {
  return (
    <div className="mb-6 flex flex-wrap items-start justify-between gap-3">
      <div>
        <h1 className="text-2xl font-semibold tracking-tight">{title}</h1>
        {description ? (
          <p className="mt-1 text-sm text-[var(--color-muted)]">{description}</p>
        ) : null}
      </div>
      {action}
    </div>
  )
}

export function EmptyState({
  title,
  description,
  actionLabel,
  actionTo,
}: {
  title: string
  description?: string
  actionLabel?: string
  actionTo?: string
}) {
  return (
    <div className="rounded-lg border border-dashed border-[var(--color-border)] bg-white px-6 py-12 text-center">
      <p className="text-base font-medium">{title}</p>
      {description ? (
        <p className="mt-1 text-sm text-[var(--color-muted)]">{description}</p>
      ) : null}
      {actionLabel && actionTo ? (
        <Link
          to={actionTo}
          className="mt-4 inline-block text-sm font-medium text-[var(--color-accent)] hover:underline"
        >
          {actionLabel}
        </Link>
      ) : null}
    </div>
  )
}

export function ErrorAlert({ message }: { message: string }) {
  return (
    <div className="mb-4 rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-800">
      {message}
    </div>
  )
}

export function LoadingBlock({ label }: { label?: string }) {
  return (
    <div className="rounded-lg border border-[var(--color-border)] bg-white px-6 py-10 text-center text-sm text-[var(--color-muted)]">
      {label ?? t('common.loading')}
    </div>
  )
}

import { useMemo } from 'react'
import { useQueries } from '@tanstack/react-query'
import {
  EmptyState,
  ErrorAlert,
  LoadingBlock,
  PageHeader,
} from '../../components/common/PageHeader'
import { useAuth } from '../../hooks/useAuth'
import { useEmployeeAssignments } from '../../hooks/useEmployeeSelf'
import { t } from '../../i18n'
import * as programsApi from '../../services/programsApi'

type CalEvent = {
  key: string
  when: Date
  label: string
  bucket: 'today' | 'tomorrow' | 'week' | 'other'
}

function startOfDay(d: Date) {
  return new Date(d.getFullYear(), d.getMonth(), d.getDate())
}

function bucketFor(when: Date, now: Date): CalEvent['bucket'] {
  const a = startOfDay(when).getTime()
  const b = startOfDay(now).getTime()
  const dayMs = 86_400_000
  if (a === b) return 'today'
  if (a === b + dayMs) return 'tomorrow'
  if (a > b && a < b + 7 * dayMs) return 'week'
  return 'other'
}

export function MyCalendarPage() {
  const { user } = useAuth()
  const {
    data: assignments = [],
    isLoading,
    error,
  } = useEmployeeAssignments(user?.id)

  const programs = useQueries({
    queries: assignments.map((a) => ({
      queryKey: ['program', a.program_id],
      queryFn: () => programsApi.getProgram(a.program_id),
    })),
  })

  const events = useMemo(() => {
    const now = new Date()
    const list: CalEvent[] = []
    assignments.forEach((a, i) => {
      const title = programs[i]?.data?.title ?? a.program_id.slice(0, 8)
      if (a.assigned_at) {
        const when = new Date(a.assigned_at)
        list.push({
          key: `${a.id}-start`,
          when,
          label: t('employeePortal.calStart', { title }),
          bucket: bucketFor(when, now),
        })
      }
      if (a.due_at) {
        const when = new Date(a.due_at)
        list.push({
          key: `${a.id}-due`,
          when,
          label: t('employeePortal.calDeadline', { title }),
          bucket: bucketFor(when, now),
        })
      }
      if (a.completed_at) {
        const when = new Date(a.completed_at)
        list.push({
          key: `${a.id}-done`,
          when,
          label: t('employeePortal.calCompleted', { title }),
          bucket: bucketFor(when, now),
        })
      }
    })
    return list.sort((x, y) => x.when.getTime() - y.when.getTime())
  }, [assignments, programs])

  if (isLoading || programs.some((q) => q.isLoading)) return <LoadingBlock />
  if (error) {
    return (
      <ErrorAlert
        message={error instanceof Error ? error.message : t('common.actionFailed')}
      />
    )
  }

  const sections: { key: CalEvent['bucket']; title: string }[] = [
    { key: 'today', title: t('employeePortal.calToday') },
    { key: 'tomorrow', title: t('employeePortal.calTomorrow') },
    { key: 'week', title: t('employeePortal.calWeek') },
  ]

  const hasVisible = sections.some((s) => events.some((e) => e.bucket === s.key))

  return (
    <div>
      <PageHeader
        title={t('employeePortal.calendarTitle')}
        description={t('employeePortal.calendarDescription')}
      />
      {!hasVisible ? (
        <EmptyState
          title={t('employeePortal.calendarEmptyTitle')}
          description={t('employeePortal.calendarEmptyDescription')}
        />
      ) : (
        <div className="space-y-6">
          {sections.map((section) => {
            const items = events.filter((e) => e.bucket === section.key)
            if (items.length === 0) return null
            return (
              <section key={section.key}>
                <h2 className="mb-2 text-sm font-semibold uppercase tracking-wide text-[var(--color-muted)]">
                  {section.title}
                </h2>
                <ul className="space-y-2">
                  {items.map((e) => (
                    <li
                      key={e.key}
                      className="rounded-lg border border-[var(--color-border)] bg-white px-4 py-3 text-sm"
                    >
                      {e.label}
                    </li>
                  ))}
                </ul>
              </section>
            )
          })}
        </div>
      )}
    </div>
  )
}

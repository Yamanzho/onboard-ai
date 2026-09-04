import { ru } from './ru'

type Params = Record<string, string | number>

function getNested(obj: unknown, path: string): unknown {
  return path.split('.').reduce<unknown>((acc, key) => {
    if (acc && typeof acc === 'object' && key in acc) {
      return (acc as Record<string, unknown>)[key]
    }
    return undefined
  }, obj)
}

/** Translate a dot-path key using the Russian catalog. Supports `{param}` interpolation. */
export function t(key: string, params?: Params): string {
  const value = getNested(ru, key)
  if (typeof value !== 'string') {
    return key
  }
  if (!params) return value
  return value.replace(/\{(\w+)\}/g, (_, name: string) =>
    params[name] !== undefined ? String(params[name]) : `{${name}}`,
  )
}

export function labelEnum(
  group: keyof typeof ru.enums,
  value: string,
): string {
  const map = ru.enums[group] as Record<string, string> | undefined
  return map?.[value] ?? value
}

export function labelEmployeeRole(role: string): string {
  return labelEnum('employeeRole', role)
}

export function labelEmployeeStatus(status: string): string {
  return labelEnum('employeeStatus', status)
}

export function labelInviteStatus(status: string): string {
  return labelEnum('inviteStatus', status)
}

export function labelAssignmentStatus(status: string): string {
  return labelEnum('assignmentStatus', status)
}

export function labelAssignmentPriority(priority: string): string {
  return labelEnum('assignmentPriority', priority)
}

export function labelArticleStatus(status: string): string {
  return labelEnum('articleStatus', status)
}

export function labelProgramStatus(isActive: boolean): string {
  return isActive
    ? t('enums.programStatus.published')
    : t('enums.programStatus.draft')
}

export function labelStepType(type: string): string {
  return labelEnum('stepType', type)
}

export function labelProgressStatus(status: string): string {
  return labelEnum('progressStatus', status)
}

export function labelReminderMode(mode: string): string {
  return labelEnum('reminderMode', mode)
}

export function labelOutboundStatus(status: string): string {
  return labelEnum('outboundStatus', status)
}

export function labelNotificationKind(kind: string): string {
  return labelEnum('notificationKind', kind)
}

export function labelSubscriptionTier(tier: string): string {
  return labelEnum('subscriptionTier', tier)
}

export function labelSubscriptionStatus(status: string): string {
  return labelEnum('subscriptionStatus', status)
}

export function labelPaymentStatus(status: string): string {
  return labelEnum('paymentStatus', status)
}

export function labelCompanyActive(isActive: boolean): string {
  return isActive ? t('enums.companyStatus.active') : t('enums.companyStatus.blocked')
}

export function labelVisibility(value: string): string {
  return labelEnum('visibility', value)
}

export { ru }

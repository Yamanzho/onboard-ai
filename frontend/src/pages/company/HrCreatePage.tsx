import { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { ErrorAlert, PageHeader } from '../../components/common/PageHeader'
import {
  EmployeeForm,
  type EmployeeFormValues,
} from '../../components/employees/EmployeeForm'
import { Button } from '../../components/ui/Button'
import { useEmployeeMutations } from '../../hooks/useEmployees'
import { useWorkspacePaths } from '../../hooks/useWorkspacePaths'
import { t } from '../../i18n'
import { ApiError } from '../../services/apiClient'
import type { Employee } from '../../types/employee'

async function copyText(value: string): Promise<void> {
  await navigator.clipboard.writeText(value)
}

/** Company Admin only — create HR via existing Invite/Employee API. */
export function HrCreatePage() {
  const navigate = useNavigate()
  const paths = useWorkspacePaths()
  const { create } = useEmployeeMutations()
  const [created, setCreated] = useState<Employee | null>(null)
  const [copyHint, setCopyHint] = useState<string | null>(null)

  async function onSubmit(values: EmployeeFormValues) {
    try {
      const telegramRaw = values.telegram_user_id.trim()
      const result: Employee = await create.mutateAsync({
        full_name: values.full_name,
        email: values.email || null,
        telegram_user_id: telegramRaw ? Number(telegramRaw) : undefined,
        role: 'hr',
        status: values.status,
      })
      setCreated(result)
    } catch (err) {
      throw new Error(
        err instanceof ApiError ? err.message : t('employees.createFailed'),
      )
    }
  }

  async function onCopy(label: string, value: string) {
    try {
      await copyText(value)
      setCopyHint(t('employees.inviteCopied', { label }))
    } catch {
      setCopyHint(t('employees.inviteCopyFailed'))
    }
  }

  return (
    <div>
      <PageHeader
        title={t('hrManagement.createTitle')}
        description={t('hrManagement.createDescription')}
      />
      {create.isError ? (
        <ErrorAlert
          message={
            create.error instanceof Error
              ? create.error.message
              : t('common.createFailed')
          }
        />
      ) : null}

      {created ? (
        <div className="space-y-4 rounded-lg border border-[var(--color-border)] bg-white p-5 text-sm">
          <h2 className="text-base font-semibold">{t('employees.inviteCreatedTitle')}</h2>
          <p>
            {t('common.status')}: <strong>{created.status}</strong> ·{' '}
            {t('common.role')}: <strong>{created.role}</strong>
          </p>
          {created.invite_email_sent ? (
            <p>
              {created.email
                ? t('employees.inviteEmailSentTo', { email: created.email })
                : t('employees.inviteEmailSent')}
            </p>
          ) : (
            <p>{t('employees.inviteSendFailed')}</p>
          )}
          {created.invite_url ? (
            <div className="space-y-2">
              <code className="block break-all rounded bg-[var(--color-bg)] p-2 text-xs">
                {created.invite_url}
              </code>
              <Button
                type="button"
                onClick={() => void onCopy(t('employees.inviteWebUrl'), created.invite_url!)}
              >
                {t('employees.copyInviteUrl')}
              </Button>
            </div>
          ) : null}
          {copyHint ? <p className="text-[var(--color-muted)]">{copyHint}</p> : null}
          <Button type="button" onClick={() => navigate(paths.hr)}>
            {t('common.back')}
          </Button>
        </div>
      ) : (
        <div className="rounded-lg border border-[var(--color-border)] bg-white p-5">
          <EmployeeForm
            initial={{
              full_name: '',
              email: '',
              telegram_user_id: '',
              role: 'hr',
              status: 'invited',
            }}
            submitLabel={t('hrManagement.new')}
            pending={create.isPending}
            roleEditable={false}
            allowedRoles={['hr']}
            onSubmit={onSubmit}
          />
        </div>
      )}
    </div>
  )
}

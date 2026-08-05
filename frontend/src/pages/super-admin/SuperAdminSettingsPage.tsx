import { useEffect, useState, type FormEvent } from 'react'
import {
  ErrorAlert,
  LoadingBlock,
  PageHeader,
} from '../../components/common/PageHeader'
import { Button } from '../../components/ui/Button'
import { Input, Label } from '../../components/ui/Field'
import {
  usePlatformSettings,
  usePlatformSettingsMutation,
} from '../../hooks/useSuperAdmin'
import { t } from '../../i18n'
import { ApiError } from '../../services/apiClient'

export function SuperAdminSettingsPage() {
  const { data, isLoading, error } = usePlatformSettings()
  const mutation = usePlatformSettingsMutation()
  const [formError, setFormError] = useState<string | null>(null)
  const [saved, setSaved] = useState(false)
  const [maintenanceMode, setMaintenanceMode] = useState(false)
  const [allowNewCompanies, setAllowNewCompanies] = useState(true)
  const [defaultTimezone, setDefaultTimezone] = useState('UTC')
  const [notes, setNotes] = useState('')

  useEffect(() => {
    if (!data) return
    setMaintenanceMode(data.maintenance_mode)
    setAllowNewCompanies(data.allow_new_companies)
    setDefaultTimezone(data.default_timezone)
    setNotes(data.notes)
  }, [data])

  async function onSubmit(e: FormEvent) {
    e.preventDefault()
    setFormError(null)
    setSaved(false)
    try {
      await mutation.mutateAsync({
        maintenance_mode: maintenanceMode,
        allow_new_companies: allowNewCompanies,
        default_timezone: defaultTimezone.trim() || 'UTC',
        notes: notes.trim(),
      })
      setSaved(true)
    } catch (err) {
      setFormError(err instanceof ApiError ? err.message : t('common.saveFailed'))
    }
  }

  return (
    <div>
      <PageHeader
        title={t('superAdmin.settings.title')}
        description={t('superAdmin.settings.description')}
      />

      {formError ? <ErrorAlert message={formError} /> : null}
      {error instanceof Error ? <ErrorAlert message={error.message} /> : null}
      {saved ? (
        <div className="mb-4 rounded-md border border-emerald-200 bg-emerald-50 px-3 py-2 text-sm text-emerald-800">
          {t('superAdmin.settings.updated')}
        </div>
      ) : null}

      {isLoading || !data ? (
        <LoadingBlock label={t('superAdmin.settings.loading')} />
      ) : (
        <form
          onSubmit={onSubmit}
          className="max-w-xl space-y-4 rounded-lg border border-[var(--color-border)] bg-white p-6"
        >
          <label className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={maintenanceMode}
              onChange={(e) => setMaintenanceMode(e.target.checked)}
            />
            {t('superAdmin.settings.maintenanceMode')}
          </label>
          <label className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              checked={allowNewCompanies}
              onChange={(e) => setAllowNewCompanies(e.target.checked)}
            />
            {t('superAdmin.settings.allowNewCompanies')}
          </label>
          <div>
            <Label htmlFor="tz">{t('superAdmin.settings.defaultTimezone')}</Label>
            <Input
              id="tz"
              value={defaultTimezone}
              onChange={(e) => setDefaultTimezone(e.target.value)}
            />
          </div>
          <div>
            <Label htmlFor="notes">{t('superAdmin.settings.notes')}</Label>
            <Input
              id="notes"
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
            />
          </div>
          <Button type="submit" disabled={mutation.isPending}>
            {mutation.isPending ? t('common.saving') : t('superAdmin.settings.save')}
          </Button>
        </form>
      )}
    </div>
  )
}

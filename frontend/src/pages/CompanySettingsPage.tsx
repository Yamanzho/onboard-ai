import { useEffect, useState, type FormEvent } from 'react'
import {
  ErrorAlert,
  LoadingBlock,
  PageHeader,
} from '../components/common/PageHeader'
import { Button } from '../components/ui/Button'
import { Input, Label } from '../components/ui/Field'
import { useAuth } from '../hooks/useAuth'
import { t } from '../i18n'
import { ApiError } from '../services/apiClient'
import * as companiesApi from '../services/companiesApi'

export function CompanySettingsPage() {
  const { user } = useAuth()
  const [loading, setLoading] = useState(true)
  const [pending, setPending] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [success, setSuccess] = useState<string | null>(null)
  const [name, setName] = useState('')
  const [timezone, setTimezone] = useState('UTC')
  const [windowStart, setWindowStart] = useState('09:00')
  const [windowEnd, setWindowEnd] = useState('18:00')
  const [quietStart, setQuietStart] = useState('')
  const [quietEnd, setQuietEnd] = useState('')
  const [companyId, setCompanyId] = useState<string | null>(null)
  const [settings, setSettings] = useState<Record<string, unknown>>({})

  useEffect(() => {
    let cancelled = false
    async function load() {
      if (!user?.company_id) return
      setLoading(true)
      setError(null)
      try {
        const company = await companiesApi.getCompany(user.company_id)
        if (cancelled) return
        setCompanyId(company.id)
        setName(company.name)
        setTimezone(company.timezone)
        setSettings(company.settings ?? {})
        const notifications = (
          company.settings as { notifications?: Record<string, string | null> } | undefined
        )?.notifications
        setWindowStart(notifications?.window_start || '09:00')
        setWindowEnd(notifications?.window_end || '18:00')
        setQuietStart(notifications?.quiet_hours_start || '')
        setQuietEnd(notifications?.quiet_hours_end || '')
      } catch (err) {
        if (!cancelled) {
          setError(
            err instanceof ApiError ? err.message : t('companySettings.loadFailed'),
          )
        }
      } finally {
        if (!cancelled) setLoading(false)
      }
    }
    void load()
    return () => {
      cancelled = true
    }
  }, [user?.company_id])

  async function onSubmit(e: FormEvent) {
    e.preventDefault()
    if (!companyId) return
    setPending(true)
    setError(null)
    setSuccess(null)
    try {
      await companiesApi.updateCompany(companyId, {
        name: name.trim(),
        timezone: timezone.trim() || 'UTC',
        settings: {
          ...settings,
          notifications: {
            window_start: windowStart.trim() || '09:00',
            window_end: windowEnd.trim() || '18:00',
            quiet_hours_start: quietStart.trim() || null,
            quiet_hours_end: quietEnd.trim() || null,
          },
        },
      })
      setSuccess(t('companySettings.saved'))
    } catch (err) {
      setError(
        err instanceof ApiError ? err.message : t('companySettings.saveFailed'),
      )
    } finally {
      setPending(false)
    }
  }

  if (loading) return <LoadingBlock />

  return (
    <div>
      <PageHeader
        title={t('companySettings.title')}
        description={t('companySettings.description')}
      />
      {error ? <ErrorAlert message={error} /> : null}
      {success ? (
        <div className="mb-4 rounded-md border border-emerald-200 bg-emerald-50 px-3 py-2 text-sm text-emerald-800">
          {success}
        </div>
      ) : null}
      <form
        onSubmit={(e) => void onSubmit(e)}
        className="max-w-xl space-y-4 rounded-lg border border-[var(--color-border)] bg-white p-5"
        noValidate
      >
        <div>
          <Label htmlFor="company_name">{t('common.name')}</Label>
          <Input
            id="company_name"
            value={name}
            onChange={(e) => setName(e.target.value)}
            required
            maxLength={255}
          />
        </div>
        <div>
          <Label htmlFor="company_timezone">{t('common.timezone')}</Label>
          <Input
            id="company_timezone"
            value={timezone}
            onChange={(e) => setTimezone(e.target.value)}
            required
            maxLength={64}
          />
        </div>
        <div className="border-t border-[var(--color-border)] pt-4">
          <h2 className="mb-3 text-sm font-semibold">
            {t('companySettings.notificationsTitle')}
          </h2>
          <div className="grid gap-4 sm:grid-cols-2">
            <div>
              <Label htmlFor="window_start">{t('companySettings.windowStart')}</Label>
              <Input
                id="window_start"
                type="time"
                value={windowStart}
                onChange={(e) => setWindowStart(e.target.value)}
                required
              />
            </div>
            <div>
              <Label htmlFor="window_end">{t('companySettings.windowEnd')}</Label>
              <Input
                id="window_end"
                type="time"
                value={windowEnd}
                onChange={(e) => setWindowEnd(e.target.value)}
                required
              />
            </div>
            <div>
              <Label htmlFor="quiet_start">{t('companySettings.quietStart')}</Label>
              <Input
                id="quiet_start"
                type="time"
                value={quietStart}
                onChange={(e) => setQuietStart(e.target.value)}
              />
            </div>
            <div>
              <Label htmlFor="quiet_end">{t('companySettings.quietEnd')}</Label>
              <Input
                id="quiet_end"
                type="time"
                value={quietEnd}
                onChange={(e) => setQuietEnd(e.target.value)}
              />
            </div>
          </div>
          <p className="mt-2 text-xs text-[var(--color-muted)]">
            {t('companySettings.quietHint')}
          </p>
        </div>
        <Button type="submit" disabled={pending}>
          {pending ? t('common.saving') : t('common.save')}
        </Button>
      </form>
    </div>
  )
}

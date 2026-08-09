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
  const [companyId, setCompanyId] = useState<string | null>(null)

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
        <Button type="submit" disabled={pending}>
          {pending ? t('common.saving') : t('common.save')}
        </Button>
      </form>
    </div>
  )
}

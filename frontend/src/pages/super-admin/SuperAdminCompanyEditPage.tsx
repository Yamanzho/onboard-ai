import { useEffect, useState, type FormEvent } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import {
  ErrorAlert,
  LoadingBlock,
  PageHeader,
} from '../../components/common/PageHeader'
import { Button } from '../../components/ui/Button'
import { Input, Label } from '../../components/ui/Field'
import {
  usePlatformCompany,
  usePlatformCompanyMutations,
} from '../../hooks/useSuperAdmin'
import { t } from '../../i18n'
import { ApiError } from '../../services/apiClient'

export function SuperAdminCompanyEditPage() {
  const { companyId } = useParams<{ companyId: string }>()
  const navigate = useNavigate()
  const { data, isLoading, error } = usePlatformCompany(companyId)
  const { update } = usePlatformCompanyMutations()
  const [formError, setFormError] = useState<string | null>(null)
  const [name, setName] = useState('')
  const [slug, setSlug] = useState('')
  const [timezone, setTimezone] = useState('UTC')

  useEffect(() => {
    if (!data) return
    setName(data.name)
    setSlug(data.slug)
    setTimezone(data.timezone)
  }, [data])

  async function onSubmit(e: FormEvent) {
    e.preventDefault()
    if (!companyId) return
    setFormError(null)
    try {
      await update.mutateAsync({
        id: companyId,
        payload: {
          name: name.trim(),
          slug: slug.trim(),
          timezone: timezone.trim() || 'UTC',
        },
      })
      navigate(`/super-admin/companies/${companyId}`, { replace: true })
    } catch (err) {
      setFormError(err instanceof ApiError ? err.message : t('common.updateFailed'))
    }
  }

  return (
    <div>
      <PageHeader
        title={t('superAdmin.companies.edit.title')}
        description={data?.name}
        action={
          <Link to={`/super-admin/companies/${companyId}`}>
            <Button variant="secondary">{t('common.cancel')}</Button>
          </Link>
        }
      />

      {formError ? <ErrorAlert message={formError} /> : null}
      {error instanceof Error ? <ErrorAlert message={error.message} /> : null}

      {isLoading || !data ? (
        <LoadingBlock label={t('superAdmin.companies.edit.loading')} />
      ) : (
        <form
          onSubmit={onSubmit}
          className="max-w-xl space-y-4 rounded-lg border border-[var(--color-border)] bg-white p-6"
        >
          <div>
            <Label htmlFor="name">{t('common.name')}</Label>
            <Input
              id="name"
              value={name}
              onChange={(e) => setName(e.target.value)}
              required
            />
          </div>
          <div>
            <Label htmlFor="slug">{t('common.slug')}</Label>
            <Input
              id="slug"
              value={slug}
              onChange={(e) => setSlug(e.target.value)}
              pattern="^[a-z0-9]+(?:-[a-z0-9]+)*$"
              required
            />
          </div>
          <div>
            <Label htmlFor="timezone">{t('common.timezone')}</Label>
            <Input
              id="timezone"
              value={timezone}
              onChange={(e) => setTimezone(e.target.value)}
              required
            />
          </div>
          <Button type="submit" disabled={update.isPending}>
            {update.isPending
              ? t('common.saving')
              : t('superAdmin.companies.edit.saveChanges')}
          </Button>
        </form>
      )}
    </div>
  )
}

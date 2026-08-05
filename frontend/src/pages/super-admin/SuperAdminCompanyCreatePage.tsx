import { useState, type FormEvent } from 'react'
import { Link, useNavigate } from 'react-router-dom'
import { ErrorAlert, PageHeader } from '../../components/common/PageHeader'
import { Button } from '../../components/ui/Button'
import { Input, Label } from '../../components/ui/Field'
import { usePlatformCompanyMutations } from '../../hooks/useSuperAdmin'
import { t } from '../../i18n'
import { ApiError } from '../../services/apiClient'

export function SuperAdminCompanyCreatePage() {
  const navigate = useNavigate()
  const { create } = usePlatformCompanyMutations()
  const [error, setError] = useState<string | null>(null)
  const [name, setName] = useState('')
  const [slug, setSlug] = useState('')
  const [timezone, setTimezone] = useState('UTC')
  const [description, setDescription] = useState('')
  const [logoUrl, setLogoUrl] = useState('')
  const [contactPerson, setContactPerson] = useState('')
  const [contactEmail, setContactEmail] = useState('')
  const [contactPhone, setContactPhone] = useState('')
  const [adminFullName, setAdminFullName] = useState('')
  const [adminEmail, setAdminEmail] = useState('')
  const [adminTelegram, setAdminTelegram] = useState('')

  async function onSubmit(e: FormEvent) {
    e.preventDefault()
    setError(null)
    const telegramId = Number(adminTelegram)
    if (!Number.isInteger(telegramId) || telegramId <= 0) {
      setError(t('superAdmin.companies.telegramInvalid'))
      return
    }
    if (!adminEmail.trim()) {
      setError(t('superAdmin.companies.adminEmailRequired'))
      return
    }
    try {
      const company = await create.mutateAsync({
        name: name.trim(),
        slug: slug.trim(),
        timezone: timezone.trim() || 'UTC',
        description: description.trim() || null,
        logo_url: logoUrl.trim() || null,
        contact_person: contactPerson.trim() || null,
        contact_email: contactEmail.trim() || null,
        contact_phone: contactPhone.trim() || null,
        admin_full_name: adminFullName.trim(),
        admin_email: adminEmail.trim(),
        admin_telegram_user_id: telegramId,
      })
      navigate(`/super-admin/companies/${company.id}`, { replace: true })
    } catch (err) {
      setError(err instanceof ApiError ? err.message : t('common.createFailed'))
    }
  }

  return (
    <div>
      <PageHeader
        title={t('superAdmin.companies.createTitle')}
        description={t('superAdmin.companies.createDescription')}
        action={
          <Link to="/super-admin/companies">
            <Button variant="secondary">{t('common.back')}</Button>
          </Link>
        }
      />
      {error ? <ErrorAlert message={error} /> : null}
      <form
        onSubmit={onSubmit}
        className="max-w-xl space-y-4 rounded-lg border border-[var(--color-border)] bg-white p-6"
      >
        <fieldset className="space-y-3">
          <legend className="text-sm font-semibold">
            {t('superAdmin.companies.companySection')}
          </legend>
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
              placeholder={t('superAdmin.companies.slugPlaceholder')}
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
          <div>
            <Label htmlFor="description">{t('common.description')}</Label>
            <Input
              id="description"
              value={description}
              onChange={(e) => setDescription(e.target.value)}
            />
          </div>
          <div>
            <Label htmlFor="logo">{t('superAdmin.companies.logoUrl')}</Label>
            <Input
              id="logo"
              type="url"
              value={logoUrl}
              onChange={(e) => setLogoUrl(e.target.value)}
              placeholder={t('superAdmin.companies.logoPlaceholder')}
            />
          </div>
        </fieldset>

        <fieldset className="space-y-3 border-t border-[var(--color-border)] pt-4">
          <legend className="text-sm font-semibold">
            {t('superAdmin.companies.contactsSection')}
          </legend>
          <div>
            <Label htmlFor="contact-person">
              {t('superAdmin.companies.contactPerson')}
            </Label>
            <Input
              id="contact-person"
              value={contactPerson}
              onChange={(e) => setContactPerson(e.target.value)}
            />
          </div>
          <div>
            <Label htmlFor="contact-email">
              {t('superAdmin.companies.contactEmail')}
            </Label>
            <Input
              id="contact-email"
              type="email"
              value={contactEmail}
              onChange={(e) => setContactEmail(e.target.value)}
            />
          </div>
          <div>
            <Label htmlFor="contact-phone">
              {t('superAdmin.companies.contactPhone')}
            </Label>
            <Input
              id="contact-phone"
              value={contactPhone}
              onChange={(e) => setContactPhone(e.target.value)}
            />
          </div>
        </fieldset>

        <fieldset className="space-y-3 border-t border-[var(--color-border)] pt-4">
          <legend className="text-sm font-semibold">
            {t('superAdmin.companies.adminSection')}
          </legend>
          <p className="text-xs text-[var(--color-muted)]">
            {t('superAdmin.companies.inviteHint')}
          </p>
          <div>
            <Label htmlFor="admin-name">{t('superAdmin.companies.fullName')}</Label>
            <Input
              id="admin-name"
              value={adminFullName}
              onChange={(e) => setAdminFullName(e.target.value)}
              required
            />
          </div>
          <div>
            <Label htmlFor="admin-email">{t('common.email')}</Label>
            <Input
              id="admin-email"
              type="email"
              value={adminEmail}
              onChange={(e) => setAdminEmail(e.target.value)}
              required
            />
          </div>
          <div>
            <Label htmlFor="admin-tg">
              {t('superAdmin.companies.telegramUserId')}
            </Label>
            <Input
              id="admin-tg"
              type="number"
              min={1}
              value={adminTelegram}
              onChange={(e) => setAdminTelegram(e.target.value)}
              required
            />
          </div>
        </fieldset>

        <Button type="submit" disabled={create.isPending}>
          {create.isPending ? t('common.creating') : t('superAdmin.companies.create')}
        </Button>
      </form>
    </div>
  )
}

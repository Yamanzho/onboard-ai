import { useEffect, useState, type FormEvent } from 'react'
import { useNavigate } from 'react-router-dom'
import { PageHeader } from '../components/common/PageHeader'
import { Button } from '../components/ui/Button'
import { Input, Label } from '../components/ui/Field'
import { useAuth } from '../hooks/useAuth'
import {
  labelEmployeeRole,
  t,
} from '../i18n'
import { ApiError } from '../services/apiClient'
import * as authApi from '../services/authApi'

export function SettingsPage() {
  const { user, refreshUser, logout } = useAuth()
  const navigate = useNavigate()

  const [fullName, setFullName] = useState(user?.full_name ?? '')
  const [email, setEmail] = useState(user?.email ?? '')
  const [profileError, setProfileError] = useState<string | null>(null)
  const [profileSuccess, setProfileSuccess] = useState<string | null>(null)
  const [profilePending, setProfilePending] = useState(false)

  const [currentPassword, setCurrentPassword] = useState('')
  const [newPassword, setNewPassword] = useState('')
  const [confirmPassword, setConfirmPassword] = useState('')
  const [securityError, setSecurityError] = useState<string | null>(null)
  const [securitySuccess, setSecuritySuccess] = useState<string | null>(null)
  const [securityPending, setSecurityPending] = useState(false)

  useEffect(() => {
    if (!user) return
    setFullName(user.full_name)
    setEmail(user.email ?? '')
  }, [user])

  async function onSaveProfile(e: FormEvent) {
    e.preventDefault()
    setProfileError(null)
    setProfileSuccess(null)
    const name = fullName.trim()
    if (!name) {
      setProfileError(t('settings.profileNameRequired'))
      return
    }
    setProfilePending(true)
    try {
      await authApi.updateMe({
        full_name: name,
        email: email.trim() || null,
      })
      await refreshUser()
      setProfileSuccess(t('settings.profileSaved'))
    } catch (err) {
      setProfileError(
        err instanceof ApiError ? err.message : t('settings.profileSaveFailed'),
      )
    } finally {
      setProfilePending(false)
    }
  }

  async function onChangePassword(e: FormEvent) {
    e.preventDefault()
    setSecurityError(null)
    setSecuritySuccess(null)
    if (newPassword.length < 8) {
      setSecurityError(t('settings.passwordMinLength'))
      return
    }
    if (newPassword !== confirmPassword) {
      setSecurityError(t('settings.passwordsMismatch'))
      return
    }
    setSecurityPending(true)
    try {
      await authApi.changePassword({
        current_password: currentPassword,
        new_password: newPassword,
        confirm_password: confirmPassword,
      })
      setSecuritySuccess(t('settings.passwordChanged'))
      setCurrentPassword('')
      setNewPassword('')
      setConfirmPassword('')
      logout()
      navigate('/login', { replace: true })
    } catch (err) {
      if (err instanceof ApiError) {
        const detail = err.message.toLowerCase()
        if (detail.includes('incorrect') || err.status === 401) {
          setSecurityError(t('settings.currentPasswordIncorrect'))
        } else if (detail.includes('different') || detail.includes('match')) {
          setSecurityError(err.message)
        } else {
          setSecurityError(t('settings.passwordChangeFailed'))
        }
      } else {
        setSecurityError(t('settings.passwordChangeFailed'))
      }
    } finally {
      setSecurityPending(false)
    }
  }

  const telegramLabel = user?.telegram_connected
    ? t('settings.telegramConnected')
    : t('settings.telegramNotConnected')

  return (
    <div>
      <PageHeader
        title={t('settings.title')}
        description={t('settings.description')}
      />

      <div className="grid max-w-2xl gap-6">
        <section className="rounded-lg border border-[var(--color-border)] bg-white p-5">
          <h2 className="mb-4 text-base font-semibold">{t('settings.profileSection')}</h2>
          <form onSubmit={(e) => void onSaveProfile(e)} className="space-y-4" noValidate>
            {profileError ? (
              <div className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-800">
                {profileError}
              </div>
            ) : null}
            {profileSuccess ? (
              <div className="rounded-md border border-emerald-200 bg-emerald-50 px-3 py-2 text-sm text-emerald-800">
                {profileSuccess}
              </div>
            ) : null}

            <div>
              <Label htmlFor="settings_full_name">{t('settings.name')}</Label>
              <Input
                id="settings_full_name"
                value={fullName}
                onChange={(e) => setFullName(e.target.value)}
                maxLength={255}
                autoComplete="name"
                required
              />
            </div>

            <div>
              <Label htmlFor="settings_email">{t('common.email')}</Label>
              <Input
                id="settings_email"
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                maxLength={320}
                autoComplete="email"
              />
            </div>

            <ReadOnlyRow
              label={t('common.role')}
              value={user?.role ? labelEmployeeRole(user.role) : t('common.emDash')}
            />
            <ReadOnlyRow
              label={t('settings.company')}
              value={user?.company_name ?? user?.company_id ?? t('common.emDash')}
            />
            <ReadOnlyRow label={t('settings.telegram')} value={telegramLabel} />

            <Button type="submit" disabled={profilePending}>
              {profilePending ? t('common.saving') : t('settings.saveChanges')}
            </Button>
          </form>
        </section>

        <section className="rounded-lg border border-[var(--color-border)] bg-white p-5">
          <h2 className="mb-4 text-base font-semibold">{t('settings.securitySection')}</h2>
          <form onSubmit={(e) => void onChangePassword(e)} className="space-y-4" noValidate>
            {securityError ? (
              <div className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-800">
                {securityError}
              </div>
            ) : null}
            {securitySuccess ? (
              <div className="rounded-md border border-emerald-200 bg-emerald-50 px-3 py-2 text-sm text-emerald-800">
                {securitySuccess}
              </div>
            ) : null}

            <div>
              <Label htmlFor="current_password">{t('settings.currentPassword')}</Label>
              <Input
                id="current_password"
                type="password"
                value={currentPassword}
                onChange={(e) => setCurrentPassword(e.target.value)}
                autoComplete="current-password"
                required
              />
            </div>
            <div>
              <Label htmlFor="new_password">{t('settings.newPassword')}</Label>
              <Input
                id="new_password"
                type="password"
                value={newPassword}
                onChange={(e) => setNewPassword(e.target.value)}
                autoComplete="new-password"
                required
                minLength={8}
              />
            </div>
            <div>
              <Label htmlFor="confirm_password">{t('settings.confirmPassword')}</Label>
              <Input
                id="confirm_password"
                type="password"
                value={confirmPassword}
                onChange={(e) => setConfirmPassword(e.target.value)}
                autoComplete="new-password"
                required
                minLength={8}
              />
            </div>

            <Button type="submit" disabled={securityPending}>
              {securityPending
                ? t('settings.changingPassword')
                : t('settings.changePassword')}
            </Button>
          </form>
        </section>
      </div>
    </div>
  )
}

function ReadOnlyRow({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt className="text-xs uppercase tracking-wide text-[var(--color-muted)]">{label}</dt>
      <dd className="mt-0.5 break-all text-sm font-medium">{value}</dd>
    </div>
  )
}

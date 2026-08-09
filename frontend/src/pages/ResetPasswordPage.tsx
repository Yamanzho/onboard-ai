import { useEffect, useState, type FormEvent } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { ErrorAlert } from '../components/common/PageHeader'
import { Button } from '../components/ui/Button'
import { Input, Label } from '../components/ui/Field'
import { useAuth } from '../hooks/useAuth'
import { t } from '../i18n'
import * as authApi from '../services/authApi'
import { ApiError } from '../services/apiClient'
import type { PasswordResetPreview } from '../types/auth'

function readResetToken(pathToken: string | undefined): string | null {
  const hash = window.location.hash.replace(/^#/, '').trim()
  if (hash) return hash
  return pathToken?.trim() || null
}

export function ResetPasswordPage() {
  const { token: pathToken } = useParams<{ token: string }>()
  const navigate = useNavigate()
  const { isAuthenticated } = useAuth()
  const [token, setToken] = useState<string | null>(() => readResetToken(pathToken))
  const [preview, setPreview] = useState<PasswordResetPreview | null>(null)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [submitError, setSubmitError] = useState<string | null>(null)
  const [password, setPassword] = useState('')
  const [confirm, setConfirm] = useState('')
  const [submitting, setSubmitting] = useState(false)

  useEffect(() => {
    const resolved = readResetToken(pathToken)
    setToken(resolved)
    if (!resolved) {
      setLoadError(t('resetPassword.invalidLink'))
      return
    }
    if (window.location.hash) {
      window.history.replaceState(
        null,
        '',
        `${window.location.pathname}${window.location.search}`,
      )
    }
    void authApi
      .previewPasswordReset(resolved)
      .then(setPreview)
      .catch((err: unknown) => {
        setLoadError(
          err instanceof ApiError ? err.message : t('resetPassword.notFound'),
        )
      })
  }, [pathToken])

  async function onSubmit(e: FormEvent) {
    e.preventDefault()
    setSubmitError(null)
    if (password.length < 8) {
      setSubmitError(t('resetPassword.passwordMinLength'))
      return
    }
    if (password !== confirm) {
      setSubmitError(t('resetPassword.passwordsMismatch'))
      return
    }
    if (!token || !preview) return

    setSubmitting(true)
    try {
      await authApi.confirmPasswordReset({
        token,
        new_password: password,
        confirm_password: confirm,
      })
      navigate('/login', { replace: true })
    } catch (err: unknown) {
      setSubmitError(
        err instanceof ApiError ? err.message : t('resetPassword.failed'),
      )
    } finally {
      setSubmitting(false)
    }
  }

  if (isAuthenticated) {
    navigate('/dashboard', { replace: true })
    return null
  }

  return (
    <div className="flex min-h-screen items-center justify-center bg-[var(--color-bg)] p-4">
      <div className="w-full max-w-md rounded-xl border border-[var(--color-border)] bg-white p-6 shadow-sm">
        <h1 className="text-lg font-semibold">{t('resetPassword.title')}</h1>
        {loadError ? (
          <div className="mt-4">
            <ErrorAlert message={loadError} />
            <Link to="/login" className="mt-3 inline-block text-sm text-[var(--color-primary)]">
              {t('common.signIn')}
            </Link>
          </div>
        ) : !preview ? (
          <p className="mt-4 text-sm text-[var(--color-muted)]">{t('common.loading')}</p>
        ) : (
          <form onSubmit={(e) => void onSubmit(e)} className="mt-4 space-y-4" noValidate>
            <p className="text-sm text-[var(--color-muted)]">
              {t('resetPassword.forUser', {
                name: preview.full_name,
                company: preview.company_name ?? t('invite.yourCompany'),
              })}
            </p>
            {submitError ? <ErrorAlert message={submitError} /> : null}
            <div>
              <Label htmlFor="reset_password">{t('settings.newPassword')}</Label>
              <Input
                id="reset_password"
                type="password"
                value={password}
                onChange={(e) => setPassword(e.target.value)}
                autoComplete="new-password"
                required
                minLength={8}
              />
            </div>
            <div>
              <Label htmlFor="reset_confirm">{t('settings.confirmPassword')}</Label>
              <Input
                id="reset_confirm"
                type="password"
                value={confirm}
                onChange={(e) => setConfirm(e.target.value)}
                autoComplete="new-password"
                required
                minLength={8}
              />
            </div>
            <Button type="submit" disabled={submitting}>
              {submitting ? t('common.saving') : t('resetPassword.submit')}
            </Button>
          </form>
        )}
      </div>
    </div>
  )
}

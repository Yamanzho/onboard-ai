import { useEffect, useState, type FormEvent } from 'react'
import { Link, useNavigate, useParams } from 'react-router-dom'
import { ErrorAlert } from '../components/common/PageHeader'
import { Button } from '../components/ui/Button'
import { Input, Label } from '../components/ui/Field'
import { useAuth } from '../hooks/useAuth'
import { t } from '../i18n'
import * as authApi from '../services/authApi'
import { ApiError } from '../services/apiClient'
import type { InvitePreview } from '../types/superAdmin'

function readInviteToken(pathToken: string | undefined): string | null {
  // Prefer fragment secret (email links: /invite#<token>) — never sent to the
  // server on navigation. Legacy path /invite/:token still works for old emails.
  const hash = window.location.hash.replace(/^#/, '').trim()
  if (hash) {
    return hash
  }
  return pathToken?.trim() || null
}

export function InviteAcceptPage() {
  const { token: pathToken } = useParams<{ token: string }>()
  const navigate = useNavigate()
  const { login, isAuthenticated } = useAuth()
  const [token, setToken] = useState<string | null>(() => readInviteToken(pathToken))
  const [preview, setPreview] = useState<InvitePreview | null>(null)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [submitError, setSubmitError] = useState<string | null>(null)
  const [password, setPassword] = useState('')
  const [confirm, setConfirm] = useState('')
  const [submitting, setSubmitting] = useState(false)

  useEffect(() => {
    const resolved = readInviteToken(pathToken)
    setToken(resolved)
    if (!resolved) {
      setLoadError(t('invite.invalidLink'))
      return
    }
    // Drop the fragment from the address bar after capturing the secret.
    if (window.location.hash) {
      window.history.replaceState(null, '', `${window.location.pathname}${window.location.search}`)
    }
    void authApi
      .previewInvite(resolved)
      .then(setPreview)
      .catch((err: unknown) => {
        setLoadError(err instanceof ApiError ? err.message : t('invite.notFound'))
      })
  }, [pathToken])

  async function onSubmit(e: FormEvent) {
    e.preventDefault()
    setSubmitError(null)
    if (password.length < 8) {
      setSubmitError(t('invite.passwordMinLength'))
      return
    }
    if (password !== confirm) {
      setSubmitError(t('invite.passwordsMismatch'))
      return
    }
    if (!token || !preview) return

    setSubmitting(true)
    try {
      const user = await authApi.acceptInvite({ token, password })
      await login(user.id, password)
      navigate('/dashboard', { replace: true })
    } catch (err: unknown) {
      setSubmitError(
        err instanceof ApiError ? err.message : t('invite.acceptFailed'),
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
        <h1 className="text-lg font-semibold">{t('invite.acceptTitle')}</h1>
        {loadError ? (
          <>
            <ErrorAlert message={loadError} />
            <Link to="/login" className="mt-4 inline-block text-sm text-[var(--color-accent)]">
              {t('invite.goToSignIn')}
            </Link>
          </>
        ) : !preview ? (
          <p className="mt-4 text-sm text-[var(--color-muted)]">{t('invite.loading')}</p>
        ) : (
          <>
            <p className="mt-2 text-sm text-[var(--color-muted)]">
              {preview.full_name}, {t('invite.setPasswordFor')}{' '}
              <strong>{preview.company_name ?? t('invite.yourCompany')}</strong>.
            </p>
            <p className="mt-1 text-xs text-[var(--color-muted)]">
              {preview.email} · {t('invite.expiresAt')}{' '}
              {new Date(preview.expires_at).toLocaleString()}
            </p>
            {submitError ? <ErrorAlert message={submitError} /> : null}
            <form onSubmit={onSubmit} className="mt-4 space-y-3">
              <div>
                <Label htmlFor="password">{t('common.password')}</Label>
                <Input
                  id="password"
                  type="password"
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  minLength={8}
                  required
                  autoComplete="new-password"
                />
              </div>
              <div>
                <Label htmlFor="confirm">{t('invite.confirmPassword')}</Label>
                <Input
                  id="confirm"
                  type="password"
                  value={confirm}
                  onChange={(e) => setConfirm(e.target.value)}
                  minLength={8}
                  required
                  autoComplete="new-password"
                />
              </div>
              <Button type="submit" className="w-full" disabled={submitting}>
                {submitting ? t('invite.settingPassword') : t('invite.setPasswordAndSignIn')}
              </Button>
            </form>
          </>
        )}
      </div>
    </div>
  )
}

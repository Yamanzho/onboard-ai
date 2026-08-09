import { useState, type FormEvent } from 'react'
import { Navigate, useNavigate } from 'react-router-dom'
import { ErrorAlert } from '../../components/common/PageHeader'
import { Button } from '../../components/ui/Button'
import { Input, Label } from '../../components/ui/Field'
import { useSuperAdminAuth } from '../../hooks/useSuperAdminAuth'
import { usePlatformPaths } from '../../hooks/useWorkspacePaths'
import { t } from '../../i18n'

export function SuperAdminLoginPage() {
  const paths = usePlatformPaths()
  const { login, isAuthenticated, loading, error, clearError } =
    useSuperAdminAuth()
  const navigate = useNavigate()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [submitting, setSubmitting] = useState(false)

  if (!loading && isAuthenticated) {
    return <Navigate to={paths.dashboard} replace />
  }

  async function onSubmit(e: FormEvent) {
    e.preventDefault()
    clearError()
    setSubmitting(true)
    try {
      await login(email, password)
      navigate(paths.dashboard, { replace: true })
    } catch {
      // error via context
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <form
      onSubmit={onSubmit}
      className="rounded-xl border border-[var(--color-border)] bg-white p-6 shadow-sm"
    >
      <p className="mb-4 text-sm text-[var(--color-muted)]">
        {t('auth.superAdminLoginHint')}
      </p>
      {error ? <ErrorAlert message={error} /> : null}
      <div className="mb-3">
        <Label htmlFor="sa-email">{t('common.email')}</Label>
        <Input
          id="sa-email"
          type="email"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          placeholder={t('auth.superAdminEmailPlaceholder')}
          required
          autoComplete="username"
        />
      </div>
      <div className="mb-5">
        <Label htmlFor="sa-password">{t('common.password')}</Label>
        <Input
          id="sa-password"
          type="password"
          value={password}
          onChange={(e) => setPassword(e.target.value)}
          required
          autoComplete="current-password"
        />
      </div>
      <Button type="submit" className="w-full" disabled={submitting}>
        {submitting ? t('common.signingIn') : t('common.signIn')}
      </Button>
    </form>
  )
}

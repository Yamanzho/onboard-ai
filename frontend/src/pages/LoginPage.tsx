import { useState, type FormEvent } from 'react'
import { Navigate, useNavigate } from 'react-router-dom'
import { ErrorAlert } from '../components/common/PageHeader'
import { Button } from '../components/ui/Button'
import { Input, Label } from '../components/ui/Field'
import { useAuth } from '../hooks/useAuth'
import { homePathForRole } from '../lib/navigation'
import { workspaceTitleKey } from '../lib/workspace'
import { t } from '../i18n'
import type { EmployeeRole } from '../types/auth'

interface LoginPageProps {
  expectedRole: EmployeeRole
}

export function LoginPage({ expectedRole }: LoginPageProps) {
  const { login, logout, isAuthenticated, loading, error, clearError, user } =
    useAuth()
  const navigate = useNavigate()
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [submitting, setSubmitting] = useState(false)
  const [roleError, setRoleError] = useState<string | null>(null)

  if (!loading && isAuthenticated) {
    return <Navigate to={homePathForRole(user?.role)} replace />
  }

  async function onSubmit(e: FormEvent) {
    e.preventDefault()
    clearError()
    setRoleError(null)
    setSubmitting(true)
    try {
      const me = await login(email.trim(), password)
      if (me.role !== expectedRole) {
        logout()
        setRoleError(t('auth.wrongLoginRole'))
        return
      }
      navigate(homePathForRole(me.role), { replace: true })
    } catch {
      // error shown via context
    } finally {
      setSubmitting(false)
    }
  }

  return (
    <form
      onSubmit={onSubmit}
      className="rounded-xl border border-[var(--color-border)] bg-white p-6 shadow-sm"
    >
      <h2 className="mb-2 text-lg font-semibold">
        {t(workspaceTitleKey(
          expectedRole === 'admin' ? 'company' : expectedRole,
        ))}
      </h2>
      <p className="mb-4 text-sm text-[var(--color-muted)]">
        {t('auth.loginHint')}
      </p>
      {error ? <ErrorAlert message={error} /> : null}
      {roleError ? <ErrorAlert message={roleError} /> : null}
      <div className="mb-3">
        <Label htmlFor="email">{t('common.email')}</Label>
        <Input
          id="email"
          type="email"
          value={email}
          onChange={(e) => setEmail(e.target.value)}
          placeholder={t('auth.emailPlaceholder')}
          required
          autoComplete="username"
        />
      </div>
      <div className="mb-5">
        <Label htmlFor="password">{t('common.password')}</Label>
        <Input
          id="password"
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

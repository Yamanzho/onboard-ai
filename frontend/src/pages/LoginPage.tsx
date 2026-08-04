import { useState, type FormEvent } from 'react'
import { Navigate, useNavigate } from 'react-router-dom'
import { ErrorAlert } from '../components/common/PageHeader'
import { Button } from '../components/ui/Button'
import { Input, Label } from '../components/ui/Field'
import { useAuth } from '../hooks/useAuth'

export function LoginPage() {
  const { login, isAuthenticated, loading, error, clearError } = useAuth()
  const navigate = useNavigate()
  const [username, setUsername] = useState('')
  const [password, setPassword] = useState('')
  const [submitting, setSubmitting] = useState(false)

  if (!loading && isAuthenticated) {
    return <Navigate to="/dashboard" replace />
  }

  async function onSubmit(e: FormEvent) {
    e.preventDefault()
    clearError()
    setSubmitting(true)
    try {
      await login(username, password)
      navigate('/dashboard', { replace: true })
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
      <p className="mb-4 text-sm text-[var(--color-muted)]">
        Sign in with employee UUID and the shared <code>AUTH_PASSWORD</code>.
      </p>
      {error ? <ErrorAlert message={error} /> : null}
      <div className="mb-3">
        <Label htmlFor="username">Employee UUID</Label>
        <Input
          id="username"
          value={username}
          onChange={(e) => setUsername(e.target.value)}
          placeholder="xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
          required
          autoComplete="username"
        />
      </div>
      <div className="mb-5">
        <Label htmlFor="password">Password</Label>
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
        {submitting ? 'Signing in…' : 'Sign in'}
      </Button>
    </form>
  )
}

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useState,
  type ReactNode,
} from 'react'
import { t } from '../i18n'
import { canAccessAdminPanel } from '../lib/roles'
import { clearTokens, getAccessToken, setTokens } from '../lib/storage'
import { ApiError } from '../services/apiClient'
import * as authApi from '../services/authApi'
import type { CurrentUser } from '../types/auth'

export interface AuthContextValue {
  user: CurrentUser | null
  loading: boolean
  error: string | null
  isAuthenticated: boolean
  login: (username: string, password: string) => Promise<void>
  logout: () => void
  clearError: () => void
}

const AuthContext = createContext<AuthContextValue | null>(null)

export function AuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<CurrentUser | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const logout = useCallback(() => {
    clearTokens()
    setUser(null)
  }, [])

  const loadMe = useCallback(async () => {
    const token = getAccessToken()
    if (!token) {
      setUser(null)
      setLoading(false)
      return
    }
    try {
      const me = await authApi.fetchMe()
      if (!canAccessAdminPanel(me.role)) {
        clearTokens()
        setUser(null)
        setError(t('auth.roleRequired'))
      } else {
        setUser(me)
      }
    } catch {
      clearTokens()
      setUser(null)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void loadMe()
  }, [loadMe])

  const login = useCallback(async (username: string, password: string) => {
    setError(null)
    try {
      const tokens = await authApi.login(username.trim(), password)
      setTokens(tokens.access_token, tokens.refresh_token)
      const me = await authApi.fetchMe()
      if (!canAccessAdminPanel(me.role)) {
        clearTokens()
        setUser(null)
        throw new Error(t('auth.roleRequired'))
      }
      setUser(me)
    } catch (err) {
      clearTokens()
      setUser(null)
      if (err instanceof ApiError) {
        setError(err.message)
      } else if (err instanceof Error) {
        setError(err.message)
      } else {
        setError(t('auth.loginFailed'))
      }
      throw err
    }
  }, [])

  const value = useMemo(
    () => ({
      user,
      loading,
      error,
      isAuthenticated: Boolean(user),
      login,
      logout,
      clearError: () => setError(null),
    }),
    [user, loading, error, login, logout],
  )

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>
}

export function useAuth(): AuthContextValue {
  const ctx = useContext(AuthContext)
  if (!ctx) throw new Error('useAuth must be used within AuthProvider')
  return ctx
}

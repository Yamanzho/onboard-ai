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
import { ApiError } from '../services/apiClient'
import * as superAdminApi from '../services/superAdminApi'
import type { SuperAdminUser } from '../types/superAdmin'

export interface SuperAdminAuthContextValue {
  user: SuperAdminUser | null
  loading: boolean
  error: string | null
  isAuthenticated: boolean
  login: (email: string, password: string) => Promise<void>
  logout: () => void
  clearError: () => void
}

const SuperAdminAuthContext = createContext<SuperAdminAuthContextValue | null>(
  null,
)

export function SuperAdminAuthProvider({ children }: { children: ReactNode }) {
  const [user, setUser] = useState<SuperAdminUser | null>(null)
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState<string | null>(null)

  const logout = useCallback(() => {
    void superAdminApi.logout().catch(() => undefined)
    setUser(null)
  }, [])

  const loadMe = useCallback(async () => {
    try {
      const me = await superAdminApi.fetchMe()
      if (me.role !== 'super_admin') {
        await superAdminApi.logout().catch(() => undefined)
        setUser(null)
        setError(t('auth.superAdminRoleRequired'))
      } else {
        setUser(me)
      }
    } catch {
      setUser(null)
    } finally {
      setLoading(false)
    }
  }, [])

  useEffect(() => {
    void loadMe()
  }, [loadMe])

  const login = useCallback(async (email: string, password: string) => {
    setError(null)
    try {
      await superAdminApi.login(email.trim(), password)
      const me = await superAdminApi.fetchMe()
      if (me.role !== 'super_admin') {
        await superAdminApi.logout().catch(() => undefined)
        setUser(null)
        throw new Error(t('auth.superAdminRoleRequired'))
      }
      setUser(me)
    } catch (err) {
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

  return (
    <SuperAdminAuthContext.Provider value={value}>
      {children}
    </SuperAdminAuthContext.Provider>
  )
}

export function useSuperAdminAuth(): SuperAdminAuthContextValue {
  const ctx = useContext(SuperAdminAuthContext)
  if (!ctx) {
    throw new Error('useSuperAdminAuth must be used within SuperAdminAuthProvider')
  }
  return ctx
}

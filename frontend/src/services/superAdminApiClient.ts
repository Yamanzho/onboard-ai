import {
  clearSuperAdminTokens,
  getSuperAdminAccessToken,
  getSuperAdminRefreshToken,
  setSuperAdminTokens,
} from '../lib/superAdminStorage'
import { ApiError } from './apiClient'

const API_BASE =
  (import.meta.env.VITE_API_BASE_URL as string | undefined)?.replace(/\/$/, '') ??
  ''

type RequestOptions = Omit<RequestInit, 'body'> & {
  body?: unknown
  auth?: boolean
}

let refreshPromise: Promise<boolean> | null = null

async function refreshSuperAdminToken(): Promise<boolean> {
  const refresh = getSuperAdminRefreshToken()
  if (!refresh) return false

  const res = await fetch(`${API_BASE}/api/v1/super-admin/auth/refresh`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ refresh_token: refresh }),
  })

  if (!res.ok) {
    clearSuperAdminTokens()
    return false
  }

  const data = (await res.json()) as {
    access_token: string
    refresh_token: string
  }
  setSuperAdminTokens(data.access_token, data.refresh_token)
  return true
}

function ensureRefresh(): Promise<boolean> {
  if (!refreshPromise) {
    refreshPromise = refreshSuperAdminToken().finally(() => {
      refreshPromise = null
    })
  }
  return refreshPromise
}

async function parseError(res: Response): Promise<ApiError> {
  let detail: unknown = null
  try {
    detail = await res.json()
  } catch {
    detail = await res.text()
  }
  const message =
    typeof detail === 'object' &&
    detail !== null &&
    'detail' in detail &&
    typeof (detail as { detail: unknown }).detail === 'string'
      ? (detail as { detail: string }).detail
      : `Request failed with status ${res.status}`
  return new ApiError(res.status, detail, message)
}

export async function superAdminRequest<T>(
  path: string,
  options: RequestOptions = {},
): Promise<T> {
  const { body, auth = true, headers, ...rest } = options
  const finalHeaders = new Headers(headers)

  if (body !== undefined) {
    finalHeaders.set('Content-Type', 'application/json')
  }

  if (auth) {
    const token = getSuperAdminAccessToken()
    if (token) finalHeaders.set('Authorization', `Bearer ${token}`)
  }

  const init: RequestInit = {
    ...rest,
    headers: finalHeaders,
    body: body === undefined ? undefined : JSON.stringify(body),
  }

  let res = await fetch(`${API_BASE}${path}`, init)

  if (res.status === 401 && auth) {
    const refreshed = await ensureRefresh()
    if (refreshed) {
      const token = getSuperAdminAccessToken()
      if (token) finalHeaders.set('Authorization', `Bearer ${token}`)
      res = await fetch(`${API_BASE}${path}`, { ...init, headers: finalHeaders })
    }
  }

  if (!res.ok) {
    throw await parseError(res)
  }

  if (res.status === 204) {
    return undefined as T
  }

  return (await res.json()) as T
}

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
  const res = await fetch(`${API_BASE}/api/v1/super-admin/auth/refresh`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    credentials: 'include',
    body: JSON.stringify({}),
  })
  return res.ok
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

  const init: RequestInit = {
    ...rest,
    credentials: 'include',
    headers: finalHeaders,
    body: body === undefined ? undefined : JSON.stringify(body),
  }

  let res = await fetch(`${API_BASE}${path}`, init)

  if (res.status === 401 && auth) {
    const refreshed = await ensureRefresh()
    if (refreshed) {
      res = await fetch(`${API_BASE}${path}`, init)
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

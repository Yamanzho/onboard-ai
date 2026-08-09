const API_BASE = (import.meta.env.VITE_API_BASE_URL as string | undefined)?.replace(/\/$/, '') ?? ''

export class ApiError extends Error {
  status: number
  detail: unknown

  constructor(status: number, detail: unknown, message?: string) {
    super(message ?? `Request failed with status ${status}`)
    this.name = 'ApiError'
    this.status = status
    this.detail = detail
  }
}

type RequestOptions = Omit<RequestInit, 'body'> & {
  body?: unknown
  auth?: boolean
  form?: boolean
}

let refreshPromise: Promise<boolean> | null = null

async function refreshAccessToken(): Promise<boolean> {
  const res = await fetch(`${API_BASE}/api/v1/auth/refresh`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    credentials: 'include',
    body: JSON.stringify({}),
  })
  return res.ok
}

function ensureRefresh(): Promise<boolean> {
  if (!refreshPromise) {
    refreshPromise = refreshAccessToken().finally(() => {
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

export async function apiRequest<T>(
  path: string,
  options: RequestOptions = {},
): Promise<T> {
  const { body, auth = true, form = false, headers, ...rest } = options
  const finalHeaders = new Headers(headers)

  if (form) {
    // browser sets multipart/form boundary; for urlencoded we set below
  } else if (body !== undefined) {
    finalHeaders.set('Content-Type', 'application/json')
  }

  const init: RequestInit = {
    ...rest,
    credentials: 'include',
    headers: finalHeaders,
    body:
      body === undefined
        ? undefined
        : form
          ? (body as BodyInit)
          : JSON.stringify(body),
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

import type { BrowserSessionResponse, CurrentUser } from '../types/auth'
import type { InviteAcceptPayload, InvitePreview } from '../types/superAdmin'
import { apiRequest } from './apiClient'

export async function login(username: string, password: string): Promise<BrowserSessionResponse> {
  const body = new URLSearchParams()
  body.set('username', username)
  body.set('password', password)

  return apiRequest<BrowserSessionResponse>('/api/v1/auth/login', {
    method: 'POST',
    auth: false,
    form: true,
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    body,
  })
}

export async function fetchMe(): Promise<CurrentUser> {
  return apiRequest<CurrentUser>('/api/v1/auth/me')
}

export async function refresh(): Promise<BrowserSessionResponse> {
  return apiRequest<BrowserSessionResponse>('/api/v1/auth/refresh', {
    method: 'POST',
    auth: false,
    body: {},
  })
}

export async function logout(): Promise<void> {
  await apiRequest<void>('/api/v1/auth/logout', {
    method: 'POST',
    auth: false,
    body: {},
  })
}

export async function previewInvite(token: string): Promise<InvitePreview> {
  return apiRequest<InvitePreview>('/api/v1/auth/invite/preview', {
    method: 'POST',
    auth: false,
    body: { token },
  })
}

export async function acceptInvite(payload: InviteAcceptPayload): Promise<CurrentUser> {
  return apiRequest<CurrentUser>('/api/v1/auth/invite/accept', {
    method: 'POST',
    auth: false,
    body: payload,
  })
}

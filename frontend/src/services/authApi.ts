import type { CurrentUser, TokenResponse } from '../types/auth'
import type { InviteAcceptPayload, InvitePreview } from '../types/superAdmin'
import { apiRequest } from './apiClient'

export async function login(username: string, password: string): Promise<TokenResponse> {
  const body = new URLSearchParams()
  body.set('username', username)
  body.set('password', password)

  return apiRequest<TokenResponse>('/api/v1/auth/login', {
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

export async function refresh(refreshToken: string): Promise<TokenResponse> {
  return apiRequest<TokenResponse>('/api/v1/auth/refresh', {
    method: 'POST',
    auth: false,
    body: { refresh_token: refreshToken },
  })
}

export async function previewInvite(token: string): Promise<InvitePreview> {
  return apiRequest<InvitePreview>(`/api/v1/auth/invite/${encodeURIComponent(token)}`, {
    auth: false,
  })
}

export async function acceptInvite(payload: InviteAcceptPayload): Promise<CurrentUser> {
  return apiRequest<CurrentUser>('/api/v1/auth/invite/accept', {
    method: 'POST',
    auth: false,
    body: payload,
  })
}

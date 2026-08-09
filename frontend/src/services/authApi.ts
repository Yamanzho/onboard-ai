import type {
  BrowserSessionResponse,
  CurrentUser,
  PasswordChangePayload,
  PasswordResetConfirmPayload,
  PasswordResetPreview,
  ProfileUpdatePayload,
} from '../types/auth'
import type { InviteAcceptPayload, InvitePreview } from '../types/superAdmin'
import { apiRequest } from './apiClient'

export async function login(email: string, password: string): Promise<BrowserSessionResponse> {
  const body = new URLSearchParams()
  // OAuth2 password form field remains "username"; value is email (or legacy UUID).
  body.set('username', email)
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

export async function updateMe(payload: ProfileUpdatePayload): Promise<CurrentUser> {
  return apiRequest<CurrentUser>('/api/v1/auth/me', {
    method: 'PATCH',
    body: payload,
  })
}

export async function changePassword(payload: PasswordChangePayload): Promise<void> {
  await apiRequest<void>('/api/v1/auth/password', {
    method: 'POST',
    body: payload,
  })
}

export async function previewPasswordReset(token: string): Promise<PasswordResetPreview> {
  return apiRequest<PasswordResetPreview>('/api/v1/auth/password/reset/preview', {
    method: 'POST',
    auth: false,
    body: { token },
  })
}

export async function confirmPasswordReset(
  payload: PasswordResetConfirmPayload,
): Promise<CurrentUser> {
  return apiRequest<CurrentUser>('/api/v1/auth/password/reset/confirm', {
    method: 'POST',
    auth: false,
    body: payload,
  })
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

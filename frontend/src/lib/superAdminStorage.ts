const ACCESS_KEY = 'onboard_sa_access_token'
const REFRESH_KEY = 'onboard_sa_refresh_token'

export function getSuperAdminAccessToken(): string | null {
  return localStorage.getItem(ACCESS_KEY)
}

export function getSuperAdminRefreshToken(): string | null {
  return localStorage.getItem(REFRESH_KEY)
}

export function setSuperAdminTokens(access: string, refresh: string): void {
  localStorage.setItem(ACCESS_KEY, access)
  localStorage.setItem(REFRESH_KEY, refresh)
}

export function clearSuperAdminTokens(): void {
  localStorage.removeItem(ACCESS_KEY)
  localStorage.removeItem(REFRESH_KEY)
}

/** @deprecated Tokens live in httpOnly cookies; kept as no-ops for compatibility. */

export function getSuperAdminAccessToken(): string | null {
  return null
}

export function getSuperAdminRefreshToken(): string | null {
  return null
}

export function setSuperAdminTokens(_access: string, _refresh: string): void {
  // no-op: server sets httpOnly cookies
}

export function clearSuperAdminTokens(): void {
  // no-op: call POST /super-admin/auth/logout to clear cookies
}

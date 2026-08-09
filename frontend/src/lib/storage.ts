/** @deprecated Tokens live in httpOnly cookies; kept as no-ops for compatibility. */

export function getAccessToken(): string | null {
  return null
}

export function getRefreshToken(): string | null {
  return null
}

export function setTokens(_access: string, _refresh: string): void {
  // no-op: server sets httpOnly cookies
}

export function clearTokens(): void {
  // no-op: call POST /auth/logout to clear cookies
}

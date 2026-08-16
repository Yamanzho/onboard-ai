import { t } from '../i18n'
import { ApiError } from '../services/apiClient'

function isAbortError(error: unknown): boolean {
  if (error instanceof DOMException && error.name === 'AbortError') return true
  if (error instanceof Error && error.name === 'AbortError') return true
  return false
}

/**
 * Map AI chat failures to safe user-facing copy.
 * Never surface stack traces, provider bodies, SQL, JWT, or raw `detail`.
 */
export function mapAIChatError(error: unknown): string {
  if (error instanceof ApiError) {
    switch (error.status) {
      case 401:
        return t('ai.errors.unauthorized')
      case 403:
        return t('ai.errors.forbidden')
      case 400:
        return t('ai.errors.badRequest')
      case 404:
        return t('ai.errors.notFound')
      case 422:
        return t('ai.errors.validation')
      case 429:
        if (error.retryAfterSeconds) {
          return t('ai.errors.rateLimitedRetry', {
            seconds: error.retryAfterSeconds,
          })
        }
        return t('ai.errors.rateLimited')
      case 503:
        return t('ai.errors.unavailable')
      case 500:
        return t('ai.errors.server')
      default:
        return t('ai.errors.generic')
    }
  }
  if (isAbortError(error) || error instanceof TypeError) {
    return t('ai.errors.network')
  }
  return t('ai.errors.network')
}

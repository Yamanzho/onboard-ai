import { Outlet } from 'react-router-dom'
import { t } from '../i18n'

export function SuperAdminAuthLayout() {
  return (
    <div className="flex min-h-screen items-center justify-center bg-[var(--color-bg)] px-4">
      <div className="w-full max-w-md">
        <div className="mb-6 text-center">
          <p className="text-sm font-semibold uppercase tracking-[0.2em] text-amber-600">
            {t('app.brand')}
          </p>
          <h1 className="mt-2 text-2xl font-semibold">{t('app.superAdmin')}</h1>
          <p className="mt-1 text-sm text-[var(--color-muted)]">
            {t('app.platformPanel')}
          </p>
        </div>
        <Outlet />
      </div>
    </div>
  )
}

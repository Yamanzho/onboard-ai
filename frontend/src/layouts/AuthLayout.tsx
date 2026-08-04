import { Outlet } from 'react-router-dom'

export function AuthLayout() {
  return (
    <div className="flex min-h-screen items-center justify-center bg-[var(--color-bg)] px-4">
      <div className="w-full max-w-md">
        <div className="mb-6 text-center">
          <p className="text-sm font-semibold uppercase tracking-[0.2em] text-[var(--color-accent)]">
            OnboardAI
          </p>
          <h1 className="mt-2 text-2xl font-semibold">Admin Panel</h1>
        </div>
        <Outlet />
      </div>
    </div>
  )
}

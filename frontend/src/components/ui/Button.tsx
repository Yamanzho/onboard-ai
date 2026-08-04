import type { ButtonHTMLAttributes, ReactNode } from 'react'

type Variant = 'primary' | 'secondary' | 'danger' | 'ghost'

const styles: Record<Variant, string> = {
  primary:
    'bg-[var(--color-accent)] text-white hover:bg-[var(--color-accent-hover)] disabled:opacity-50',
  secondary:
    'bg-white border border-[var(--color-border)] text-[var(--color-text)] hover:bg-slate-50 disabled:opacity-50',
  danger:
    'bg-[var(--color-danger)] text-white hover:bg-red-800 disabled:opacity-50',
  ghost: 'bg-transparent text-[var(--color-muted)] hover:text-[var(--color-text)]',
}

interface ButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: Variant
  children: ReactNode
}

export function Button({
  variant = 'primary',
  className = '',
  children,
  ...props
}: ButtonProps) {
  return (
    <button
      className={`inline-flex items-center justify-center rounded-md px-3 py-2 text-sm font-medium transition ${styles[variant]} ${className}`}
      {...props}
    >
      {children}
    </button>
  )
}

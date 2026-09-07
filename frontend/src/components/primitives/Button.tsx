import type { ButtonHTMLAttributes } from 'react';

type Variant = 'default' | 'primary' | 'ghost';

const VARIANT: Record<Variant, string> = {
  default: 'border border-border bg-card-raised text-accent-light hover:bg-white/[0.06]',
  primary: 'bg-accent text-white hover:bg-accent-light',
  ghost: 'text-muted hover:text-body',
};

export function Button({
  variant = 'default',
  loading = false,
  loadingLabel = 'Working...',
  className = '',
  children,
  disabled,
  type: _type,
  ...rest
}: ButtonHTMLAttributes<HTMLButtonElement> & { variant?: Variant; loading?: boolean; loadingLabel?: string }) {
  return (
    <button
      type="button"
      disabled={disabled || loading}
      className={`rounded px-3 py-1.5 text-xs font-semibold transition disabled:opacity-50 ${VARIANT[variant]} ${className}`.trim()}
      {...rest}
    >
      {loading ? loadingLabel : children}
    </button>
  );
}

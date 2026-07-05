/**
 * Dashboard metric card — displays a single KTSL metric with status indicator.
 *
 * Suprematist variant styles mc-0 through mc-5 alternate between paper/white
 * backgrounds and different border/status hues for visual rhythm. A diagonal
 * diamond accent sits in the top-right corner.
 */

export interface MetricsCardProps {
  label: string
  value: string | number
  status: 'ok' | 'warn' | 'error'
  icon?: string
  /** Variant 0-5 determines border/bg/diamond colour */
  variant?: 0 | 1 | 2 | 3 | 4 | 5
}

const variantStyles: Record<number, { wrap: string; diamond: string; val: string }> = {
  0: { wrap: 'bg-paper border-amber', diamond: 'bg-gold', val: 'text-amber-800' },
  1: { wrap: 'bg-white border-primary', diamond: 'bg-primary', val: 'text-primary' },
  2: { wrap: 'bg-paper border-amber-700', diamond: 'bg-amber', val: 'text-amber-800' },
  3: { wrap: 'bg-white border-indigo', diamond: 'bg-indigo', val: 'text-indigo' },
  4: { wrap: 'bg-paper border-forest', diamond: 'bg-forest', val: 'text-forest' },
  5: { wrap: 'bg-white border-ink', diamond: 'bg-ink', val: 'text-ink' },
}

const statusLabel: Record<MetricsCardProps['status'], string> = {
  ok: '✓ NORMAL',
  warn: '⚠ WARNING',
  error: '✗ CRITICAL',
}

const statusClass: Record<MetricsCardProps['status'], string> = {
  ok: 'text-forest',
  warn: 'text-amber-800',
  error: 'text-brick',
}

export default function MetricsCard({ label, value, status, icon, variant = 0 }: MetricsCardProps) {
  const vs = variantStyles[variant] ?? variantStyles[0]
  return (
    <div
      className={`relative cursor-default border-2 p-5 transition-all hover:-translate-x-0.5 hover:-translate-y-0.5 hover:shadow-[6px_6px_0_#F59E0B] hover:border-indigo ${vs.wrap}`}
    >
      {/* Diamond accent */}
      <span className={`absolute -top-1 -right-1 h-4 w-4 rotate-45 ${vs.diamond}`} />
      {icon && <span className="mb-2 block text-2xl">{icon}</span>}
      <div className="mb-1.5 font-body text-[11px] font-black uppercase tracking-wider text-muted">{label}</div>
      <div className={`text-[36px] font-black leading-none tracking-tight ${vs.val}`}>{value}</div>
      <div className={`mt-1.5 text-[10px] font-bold tracking-wide ${statusClass[status]}`}>
        {statusLabel[status]}
      </div>
    </div>
  )
}

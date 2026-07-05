/**
 * Dashboard alert feed — displays the most recent violations/warnings.
 *
 * Each alert has a coloured vertical severity bar on the left edge
 * (amber = warning, forest = success, brick = error).
 *
 * Suprematist style: bold text, subtle paper background on hover.
 */

import type { AuditEntry } from '@/types/ktsl'

export interface AlertFeedProps {
  violations: AuditEntry[]
  maxItems?: number
}

const severityBar: Record<string, string> = {
  info: 'bg-indigo',
  warning: 'bg-gold',
  error: 'bg-brick',
}

export default function AlertFeed({ violations, maxItems = 5 }: AlertFeedProps) {
  const shown = violations.slice(-maxItems).reverse()
  return (
    <div className="flex flex-col gap-0">
      {shown.length === 0 && (
        <p className="font-body text-sm text-muted">No alerts — session is clean.</p>
      )}
      {shown.map((v) => {
        const barColor = severityBar[v.severity ?? 'info'] ?? 'bg-gold'
        return (
          <div
            key={v.id}
            className="relative flex items-center border-[1.5px] border-line bg-white transition-colors hover:bg-paper -mt-[1.5px] first:mt-0"
          >
            <div className={`self-stretch w-1.5 mr-3.5 -my-[1px] -ml-[1.5px] ${barColor}`} />
            <div className="flex-1 py-3.5 pr-4">
              <div className="text-[13px] font-bold">
                <span className="mr-1.5 font-mono font-black text-indigo">#{v.event_id ?? v.id}</span>
                {v.message}
              </div>
              {v.caused_by_event_ids && v.caused_by_event_ids.length > 0 && (
                <p className="mt-0.5 font-body text-xs font-normal text-muted">
                  前置事件 {v.caused_by_event_ids.map((id) => `#${id}`).join(', ')} 未提交
                </p>
              )}
            </div>
            <div className="pr-4 font-mono text-[11px] text-muted whitespace-nowrap">2m ago</div>
          </div>
        )
      })}
    </div>
  )
}

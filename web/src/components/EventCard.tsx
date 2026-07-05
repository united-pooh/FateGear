/**
 * Session page event card — displays a single committed event with status.
 *
 * Phase 8: will include action buttons (Override / Rollback / Allow+Flag)
 * for events with warnings or violations.
 */

import type { EventRecord } from '@/types/ktsl'

export interface EventCardProps {
  event: EventRecord
  status: 'allowed' | 'warn' | 'error'
  violations?: string[]
}

const statusBadge: Record<EventCardProps['status'], string> = {
  allowed: 'bg-green-100 text-green-800',
  warn: 'bg-yellow-100 text-yellow-800',
  error: 'bg-red-100 text-red-800',
}

const statusIcon: Record<EventCardProps['status'], string> = {
  allowed: '✅',
  warn: '⚠️',
  error: '❌',
}

export default function EventCard({ event, status, violations }: EventCardProps) {
  return (
    <div className="rounded-lg border border-gray-200 bg-white p-4 shadow-sm">
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-2">
          <span className="font-medium">{event.actor ?? 'Unknown'}</span>
          <span className="text-sm text-gray-500">@{event.scene_id}</span>
        </div>
        <span
          className={`rounded-full px-2 py-0.5 text-xs font-medium ${statusBadge[status]}`}
        >
          {statusIcon[status]} {status.toUpperCase()}
        </span>
      </div>
      <p className="mt-2 text-gray-800">{event.action_text}</p>
      {event.output_info_ids && event.output_info_ids.length > 0 && (
        <p className="mt-1 text-sm text-gray-500">
          → 获得信息: {event.output_info_ids.join(', ')}
        </p>
      )}
      {violations && violations.length > 0 && (
        <ul className="mt-2 list-inside list-disc text-sm text-red-600">
          {violations.map((v, i) => (
            <li key={i}>{v}</li>
          ))}
        </ul>
      )}
    </div>
  )
}

/**
 * Timeline page — multi-scene parallel track view.
 *
 * Each scene is a horizontal track; events are positioned by time_minute.
 * Phase 8: will add zoom controls, event detail panel on click, and
 * barrier/coupling indicators.
 */

import type { EventSummary } from '@/types/ktsl'

export interface TimelineTrackProps {
  sceneId: string
  sceneName?: string
  events: EventSummary[]
  totalMinutes?: number
}

export default function TimelineTrack({
  sceneId,
  sceneName,
  events,
  totalMinutes = 120,
}: TimelineTrackProps) {
  return (
    <div className="mb-4 rounded-lg border border-gray-200 bg-white p-4">
      <div className="mb-2 flex items-center justify-between">
        <h3 className="text-sm font-semibold">{sceneName ?? sceneId}</h3>
        <span className="text-xs text-gray-500">
          {events.length} event{events.length !== 1 ? 's' : ''}
        </span>
      </div>
      <div className="relative h-12 rounded bg-gray-50">
        {/* Time axis */}
        <div className="absolute inset-x-0 top-0 h-px bg-gray-200" />
        {/* Event markers */}
        {events.map((ev) => {
          const pct = totalMinutes > 0 ? (ev.time_minute ?? 0) / totalMinutes : 0
          const left = `${Math.min(Math.max(pct * 100, 2), 98)}%`
          const hasViolation = ev.status === 'blocked' || ev.status === 'retconned'
          return (
            <div
              key={ev.event_id}
              className="group absolute top-1/2 -translate-y-1/2"
              style={{ left }}
              title={ev.action_text}
            >
              <div
                className={`h-3 w-3 rounded-full ${
                  hasViolation ? 'bg-red-500' : 'bg-blue-500'
                }`}
              />
              <div className="absolute -top-8 left-1/2 hidden -translate-x-1/2 whitespace-nowrap rounded bg-gray-800 px-2 py-0.5 text-xs text-white group-hover:block">
                #{ev.event_index} {ev.action_text}
              </div>
            </div>
          )
        })}
      </div>
    </div>
  )
}

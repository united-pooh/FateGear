/**
 * Page C: Timeline
 *
 * Multi-scene parallel timeline view — each scene is a horizontal track;
 * events are positioned by time_minute. Barrier markers drawn as red
 * vertical lines. Click event → detail panel (static selection in mock).
 *
 * Suprematist style: bold event blocks, amber time ruler, diagonal accents.
 */

import { useState } from 'react'

interface EventBlock {
  id: string
  actor: string
  actionText: string
  minute: number
  status: 'ok' | 'warn' | 'err' | 'idle'
}

interface Track {
  sceneId: string
  sceneName: string
  meta: string
  events: EventBlock[]
  locked?: boolean
  barrierMarkerPct?: number
  barrierLabel?: string
}

const tracks: Track[] = [
  {
    sceneId: 'hospital_records',
    sceneName: 'hospital_records',
    meta: '2 committed · barrier B1 ✓',
    events: [
      { id: 'S001', actor: '佐藤', actionText: '翻找档案柜', minute: 0, status: 'ok' },
      { id: 'S004', actor: '佐藤', actionText: '追问医生', minute: 28, status: 'ok' },
    ],
    barrierMarkerPct: 65,
    barrierLabel: 'B1 ✓',
  },
  {
    sceneId: 'street',
    sceneName: 'street',
    meta: '2 committed · 1 warned',
    events: [
      { id: 'S002', actor: '李', actionText: '跟踪医生', minute: 5, status: 'ok' },
      { id: 'S003', actor: '李', actionText: '偷听对话', minute: 17, status: 'warn' },
    ],
  },
  {
    sceneId: 'old_house',
    sceneName: 'old_house',
    meta: '🔒 LOCKED',
    events: [],
    locked: true,
  },
]

const TOTAL_MINUTES = 50

const statusStyles: Record<string, string> = {
  ok: 'bg-forest border-ink text-white',
  warn: 'bg-gold border-ink text-ink',
  err: 'bg-brick border-ink text-white',
  idle: 'bg-sand border-line border-dashed text-muted',
}

export default function Timeline() {
  const [selectedEvent, setSelectedEvent] = useState<string | null>('S003')
  const selected = tracks
    .flatMap((t) => t.events)
    .find((e) => e.id === selectedEvent)

  return (
    <div>
      <h1 className="text-[22px] font-black">Scene Timeline</h1>
      <p className="mb-7 mt-1.5 font-body text-[11px] uppercase tracking-[2px] text-muted">
        Multi-track · police_hospital_old_house · 8 events
      </p>

      {/* Timeline container */}
      <div className="border-2 border-line bg-white">
        {/* Time ruler */}
        <div className="flex items-center gap-5 border-b-2 border-line bg-paper px-5 py-3">
          <span className="text-[9px] font-black uppercase tracking-[2px] text-muted">Time</span>
          <div className="relative flex-1 border-b-2 border-line h-6">
            {[0, 10, 20, 30, 40, 50].map((tick) => (
              <span
                key={tick}
                className="absolute font-mono text-[10px] text-muted"
                style={{ left: `${(tick / TOTAL_MINUTES) * 100}%`, transform: 'translateX(-50%)' }}
              >
                {tick}'
                <span className="absolute -bottom-1 left-1/2 h-1.5 w-px bg-line" />
              </span>
            ))}
          </div>
        </div>

        {/* Track rows */}
        {tracks.map((track) => (
          <div
            key={track.sceneId}
            className={`flex border-b-2 border-line last:border-b-0 min-h-[64px]`}
          >
            {/* Track label */}
            <div
              className={`w-[180px] shrink-0 border-r-2 border-line p-5 flex flex-col justify-center ${
                track.locked ? 'bg-primary text-white' : 'bg-sand'
              }`}
            >
              <div className="text-[13px] font-black tracking-wide">{track.sceneName}</div>
              <div className={`mt-1 font-body text-[10px] ${track.locked ? 'text-white/80' : 'text-muted'}`}>
                {track.meta}
              </div>
            </div>

            {/* Track area */}
            {track.locked ? (
              <div
                className="flex flex-1 items-center justify-center gap-2 font-body text-sm text-muted"
                style={{
                  background:
                    'repeating-linear-gradient(45deg,var(--sand),var(--sand) 8px,var(--paper) 8px,var(--paper) 16px)',
                }}
              >
                <span className="text-lg">🔒</span>
                Needs barrier B1 (hospital_records → old_house)
              </div>
            ) : (
              <div className="relative flex flex-1 items-center gap-2 px-4 py-3 bg-white">
                {track.events.map((ev) => (
                  <button
                    key={ev.id}
                    type="button"
                    onClick={() => setSelectedEvent(ev.id)}
                    className={`relative z-10 min-w-[140px] border-2 px-3 py-2 text-left transition-transform hover:-translate-x-0.5 hover:-translate-y-0.5 hover:shadow-[3px_3px_0_#FBBF24] ${statusStyles[ev.status]} ${
                      selectedEvent === ev.id ? 'ring-2 ring-indigo ring-offset-1' : ''
                    }`}
                    style={{ marginLeft: `${(ev.minute / TOTAL_MINUTES) * 100}%` }}
                  >
                    <div className="font-mono text-[10px] font-black tracking-wider">#{ev.id}</div>
                    <div className="text-xs font-black leading-tight">{ev.actor}</div>
                    <div className="font-body text-[10px] leading-tight opacity-85">{ev.actionText}</div>
                  </button>
                ))}
                {/* Idle placeholder */}
                <div
                  className={`min-w-[140px] border-2 border-dashed border-line bg-sand px-3 py-2 text-left text-muted ${statusStyles.idle}`}
                  style={{ marginLeft: '20%' }}
                >
                  <div className="font-mono text-[10px] font-black tracking-wider">#E___</div>
                  <div className="text-xs font-black leading-tight">—</div>
                  <div className="font-body text-[10px] leading-tight opacity-85">等待行动</div>
                </div>
                {/* Barrier marker */}
                {track.barrierMarkerPct !== undefined && (
                  <div
                    className="absolute top-0 z-20 h-full w-0.5 bg-primary"
                    style={{ left: `${track.barrierMarkerPct}%` }}
                  >
                    <span className="absolute -top-5 left-1/2 -translate-x-1/2 whitespace-nowrap border border-primary bg-paper px-1 font-mono text-[9px] font-black text-primary">
                      {track.barrierLabel}
                    </span>
                  </div>
                )}
              </div>
            )}
          </div>
        ))}
      </div>

      {/* Event detail panel */}
      <div className="mt-6 border-2 border-line bg-white p-5">
        <div className="mb-4 text-[9px] font-black uppercase tracking-[3px] text-muted">
          Event Detail
        </div>
        {selected ? (
          <div className="grid grid-cols-2 gap-5">
            <div>
              <div className="mb-2 font-mono text-[11px] font-black text-indigo">
                #{selected.id} · {selected.actor} · street
              </div>
              <div className="mb-2 text-lg font-black leading-snug">"{selected.actionText}"</div>
              <div className="mb-4 font-body text-sm leading-relaxed text-muted">
                Visibility: public · Time elapsed: {selected.minute} min
              </div>
              <div className="font-body text-[11px] text-muted">
                <strong className="text-ink">Output:</strong> info_07-summary (low, partial) · info_12
                hint (high, leaked)
              </div>
            </div>
            <div className="border-l-[3px] border-line pl-5">
              <div className="mb-2 text-[9px] font-bold uppercase tracking-[2px] text-brick">
                Violation
              </div>
              <div className="border-2 border-gold bg-paper p-3 font-body text-sm leading-relaxed font-bold text-amber-800">
                ⚠ 因果违反: 前置事件 #E_barrier 未满足
                <br />
                ⚠ 信息泄露: actor {selected.actor} 可能推断 info_12 (high sensitivity)
                <br />
                ℹ Spot gap: 当前 scene dwell 8min (threshold 30min)
              </div>
            </div>
          </div>
        ) : (
          <p className="font-body text-sm text-muted">点击事件查看详情</p>
        )}
      </div>
    </div>
  )
}

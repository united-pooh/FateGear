/**
 * Page B: Session
 *
 * KP submits actions and sees real-time audit feedback — the graphical
 * version of the CLI `ktsl session` REPL.
 *
 * Suprematist style: event cards with colored left border (green=ok,
 * amber=warn, red=err). Bottom-anchored action submission bar on a
 * paper background with bold primary submit button.
 */

import { useState } from 'react'
import type { ActionInput, EventRecord, Visibility } from '@/types/ktsl'
import { mockEvents } from '@/mock/data'

interface EventWithStatus {
  event: EventRecord
  status: 'allowed' | 'warn' | 'error'
  warningText?: string
  warningHints?: string[]
}

const mockEventStream: EventWithStatus[] = [
  {
    event: mockEvents[0],
    status: 'allowed',
  },
  {
    event: mockEvents[1],
    status: 'allowed',
  },
  {
    event: mockEvents[2],
    status: 'warn',
    warningText: '⚠ 潜在泄露: 李 可能从对话内容推断出信息_12（高敏感）。当前未正式授权。',
    warningHints: ['info_07-summary (low, partial)', '⚠ hint: info_12 尸体位置 (high)'],
  },
  {
    event: mockEvents[3],
    status: 'allowed',
  },
  {
    event: mockEvents[4],
    status: 'allowed',
  },
]

const statusBadge: Record<EventWithStatus['status'], string> = {
  allowed: 'text-forest',
  warn: 'text-amber-800',
  error: 'text-brick',
}

const statusLabel: Record<EventWithStatus['status'], string> = {
  allowed: '✓ COMMITTED',
  warn: '⚠ FLAGGED',
  error: '✗ BLOCKED',
}

const statusBorder: Record<EventWithStatus['status'], string> = {
  allowed: 'border-l-forest',
  warn: 'border-l-gold border-gold',
  error: 'border-l-brick',
}

export default function Session() {
  const [actionText, setActionText] = useState('')
  const [actor, setActor] = useState('佐藤')
  const [sceneId, setSceneId] = useState('street')
  const [visibility, setVisibility] = useState<Visibility>('public')

  function handleSubmit(e: React.FormEvent) {
    e.preventDefault()
    if (!actionText || !actor || !sceneId) return
    const input: ActionInput = { action: actionText, actor, scene_id: sceneId, visibility }
    // In Phase 8 we just log — wiring to mutation comes later
    console.log('[Session] submit:', input)
    setActionText('')
  }

  return (
    <div className="flex h-[calc(100vh-72px)] flex-col">
      {/* Top bar */}
      <div className="mb-6 flex items-start justify-between">
        <h1 className="text-[22px] font-black">
          Session: police_hospital
          <span className="ml-2 inline-block border-2 border-line bg-paper px-2.5 py-0.5 align-middle font-mono text-sm font-bold">
            street
          </span>
        </h1>
        <div className="flex items-center gap-5">
          <div className="text-center">
            <div className="text-lg font-black text-indigo">8</div>
            <div className="font-body text-[9px] uppercase tracking-widest text-muted">Events</div>
          </div>
          <div className="h-8 w-px bg-line" />
          <div className="text-center">
            <div className="text-lg font-black text-forest">OK</div>
            <div className="font-body text-[9px] uppercase tracking-widest text-muted">Status</div>
          </div>
        </div>
      </div>

      {/* Event scroll area */}
      <div className="mb-4 flex-1 space-y-3.5 overflow-y-auto pr-2">
        {mockEventStream.map(({ event, status, warningText, warningHints }) => (
          <div
            key={event.id}
            className={`border-2 border-line border-l-[6px] bg-white p-4 relative ${statusBorder[status]}`}
          >
            <div className="mb-2 flex items-center gap-3">
              <span className="border-[1.5px] border-line bg-paper px-2 py-0.5 font-mono text-[13px] font-black text-indigo">
                #{event.id}
              </span>
              <span className="text-sm font-black">{event.actor}</span>
              <span className="border border-line bg-sand px-2 py-0.5 font-mono text-[11px] text-muted">
                {event.scene_id}
              </span>
              <span className={`ml-auto text-[10px] font-black uppercase tracking-wider ${statusBadge[status]}`}>
                {statusLabel[status]}
              </span>
            </div>
            <p className="mb-2 text-sm leading-relaxed">{event.action_text}</p>
            {event.output_info_ids && event.output_info_ids.length > 0 && (
              <div className="flex flex-wrap gap-1.5">
                {event.output_info_ids.map((info) => (
                  <span
                    key={info}
                    className="border border-line bg-sand px-1.5 py-0.5 font-body text-[11px] text-muted"
                  >
                    → {info}
                  </span>
                ))}
                {event.id === 'E004' && (
                  <>
                    <span className="border border-line bg-sand px-1.5 py-0.5 font-body text-[11px] text-muted">
                      → barrier B1 satisfied ✓
                    </span>
                    <span className="border border-line bg-sand px-1.5 py-0.5 font-body text-[11px] text-muted">
                      → coupling C1 triggered
                    </span>
                  </>
                )}
              </div>
            )}
            {/* Warning box */}
            {warningText && (
              <div className="mt-2.5 border-2 border-gold bg-paper px-3.5 py-2.5 font-body text-xs font-bold text-amber-800">
                {warningText}
                {warningHints && warningHints.length > 0 && (
                  <div className="mt-2 flex flex-wrap gap-1.5">
                    {warningHints.map((h) => (
                      <span
                        key={h}
                        className={`border px-1.5 py-0.5 text-[11px] ${
                          h.startsWith('⚠')
                            ? 'border-brick text-brick'
                            : 'border-line bg-sand text-muted'
                        }`}
                      >
                        {h}
                      </span>
                    ))}
                  </div>
                )}
                <div className="mt-2 flex gap-2">
                  <WarnButton label="OVERRIDE" />
                  <WarnButton label="ROLLBACK" />
                  <WarnButton label="ALLOW+FLAG" />
                </div>
              </div>
            )}
          </div>
        ))}
        {/* Upcoming placeholder */}
        <div className="border-2 border-dashed border-line bg-sand py-8 text-center font-body text-sm text-muted">
          等待下一个行动...
        </div>
      </div>

      {/* Bottom action submit bar */}
      <form
        onSubmit={handleSubmit}
        className="border-[3px] border-ink bg-paper p-4 flex items-end gap-3"
      >
        <SubmitField label="行动描述" className="flex-[2]">
          <input
            type="text"
            placeholder='例: 佐藤 "翻找档案柜"'
            value={actionText}
            onChange={(e) => setActionText(e.target.value)}
            className="w-full border-2 border-line bg-white px-3 py-2.5 text-[13px] font-body outline-none focus:border-indigo"
          />
        </SubmitField>
        <SubmitField label="角色">
          <select
            value={actor}
            onChange={(e) => setActor(e.target.value)}
            className="w-full border-2 border-line bg-white px-3 py-2.5 text-[13px] font-body outline-none focus:border-indigo"
          >
            <option>佐藤</option>
            <option>李</option>
            <option>王</option>
          </select>
        </SubmitField>
        <SubmitField label="场景">
          <select
            value={sceneId}
            onChange={(e) => setSceneId(e.target.value)}
            className="w-full border-2 border-line bg-white px-3 py-2.5 text-[13px] font-body outline-none focus:border-indigo"
          >
            <option>hospital_records</option>
            <option>street</option>
            <option>hospital_wing</option>
            <option disabled>old_house 🔒</option>
          </select>
        </SubmitField>
        <SubmitField label="可见性">
          <select
            value={visibility}
            onChange={(e) => setVisibility(e.target.value as Visibility)}
            className="w-full border-2 border-line bg-white px-3 py-2.5 text-[13px] font-body outline-none focus:border-indigo"
          >
            <option value="public">public</option>
            <option value="private">private</option>
            <option value="keeper">keeper</option>
          </select>
        </SubmitField>
        <button
          type="submit"
          className="bg-primary px-7 py-2.5 text-sm font-black tracking-wide text-white transition-all hover:-translate-x-0.5 hover:-translate-y-0.5 hover:bg-indigo hover:shadow-[4px_4px_0_#F59E0B]"
        >
          提交 →
        </button>
      </form>
    </div>
  )
}

function SubmitField({ label, children, className }: { label: string; children: React.ReactNode; className?: string }) {
  return (
    <div className={className}>
      <label className="mb-1.5 block text-[10px] font-black uppercase tracking-[2px] text-muted">
        {label}
      </label>
      {children}
    </div>
  )
}

function WarnButton({ label }: { label: string }) {
  return (
    <button
      type="button"
      className="border-2 border-ink bg-white px-3.5 py-1.5 text-[11px] font-bold font-body transition-colors hover:bg-indigo hover:text-bg"
    >
      {label}
    </button>
  )
}

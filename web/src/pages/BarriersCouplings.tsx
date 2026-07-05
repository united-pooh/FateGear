/**
 * Page E: Barriers & Couplings
 *
 * Runtime status panel showing which barriers are waiting / satisfied and
 * which couplings are active / locked.
 *
 * Suprematist style: bold status badges with fill accents, paper
 * background for waiting/blocked cards.
 */

import type { BarrierStatus, CouplingMode } from '@/types/ktsl'
import { mockBarrierStates, mockCouplingStates } from '@/mock/data'

const barrierDetail: Record<string, { name: string; conditions: { text: string; met: boolean; icon: string }[]; sceneFrom: string; sceneTo: string }> = {
  B1: {
    name: 'hospital_records → street',
    sceneFrom: 'hospital_records',
    sceneTo: 'street',
    conditions: [
      { text: 'event #S001 "#E001 committed"', met: true, icon: '●' },
      { text: 'event #S004 "#E004 committed"', met: true, icon: '●' },
    ],
  },
  B2: {
    name: 'street → old_house',
    sceneFrom: 'street',
    sceneTo: 'old_house',
    conditions: [
      { text: 'event #E008 "李进入老宅"', met: false, icon: '○' },
    ],
  },
  B3: {
    name: 'hospital_wing → old_house',
    sceneFrom: 'hospital_wing',
    sceneTo: 'old_house',
    conditions: [
      { text: 'info_07 "档案记录" committed', met: false, icon: '○' },
    ],
  },
}

const couplingDetail: Record<string, { name: string; score: number; sharedChars: string; drift: number; threshold: number; locked?: boolean; note?: string }> = {
  C1: {
    name: 'hospital ↔ street',
    score: 0.85,
    sharedChars: '佐藤, 李',
    drift: 5,
    threshold: 15,
  },
  C2: {
    name: 'street → old_house',
    score: 0.40,
    sharedChars: '—',
    drift: 0,
    threshold: 15,
    locked: true,
    note: '🔒 Locked until B2 satisfied',
  },
  C3: {
    name: 'hospital_wing → hospital_records',
    score: 0.10,
    sharedChars: '—',
    drift: 0,
    threshold: 15,
  },
}

function barrierStatusBadge(status: BarrierStatus): { label: string; cls: string } {
  switch (status) {
    case 'satisfied': return { label: 'SATISFIED ✓', cls: 'bg-forest text-white border-forest' }
    case 'waiting': return { label: 'WAITING', cls: 'bg-gold text-ink border-amber-700' }
    case 'blocked': return { label: 'LOCKED', cls: 'bg-brick text-white border-red-800' }
    default: return { label: 'OPEN', cls: 'sand text-muted border-line' }
  }
}

function modeTagClass(_mode: CouplingMode): string {
  return 'font-body text-[9px] font-bold tracking-wider border-[1.5px] border-line px-1.5 py-0.5 text-muted'
}

export default function BarriersCouplings() {
  const barriers = mockBarrierStates
  const couplings = mockCouplingStates

  return (
    <div>
      <h1 className="text-[22px] font-black">Barriers & Couplings</h1>
      <p className="mb-7 mt-1.5 font-body text-[11px] uppercase tracking-[2px] text-muted">
        Runtime State · Session SESS-2026-07-04-A1F3
      </p>

      <div className="grid grid-cols-2 gap-6">
        {/* LEFT: Barriers */}
        <div>
          <div className="relative mb-4 pl-4 text-[10px] font-black uppercase tracking-[3px] text-muted">
            <span className="absolute left-0 top-1/2 h-2 w-2 -translate-y-1/2 rotate-45 bg-primary" />
            Barriers ({barriers.length})
          </div>

          {barriers.map((b) => {
            const det = barrierDetail[b.barrier_id]
            if (!det) return null
            const badge = barrierStatusBadge(b.status)
            const metCount = det.conditions.filter((c) => c.met).length
            const pct = (metCount / det.conditions.length) * 100
            const fillColor = b.status === 'satisfied' ? 'bg-forest' : b.status === 'waiting' ? 'bg-gold' : 'bg-brick'
            return (
              <div
                key={b.barrier_id}
                className={`mb-3 border-2 bg-white ${
                  b.status === 'satisfied' ? 'border-forest' : 'border-line'
                }`}
              >
                <div className="flex items-center justify-between border-b-2 border-line px-4 py-3.5">
                  <span className="text-[13px] font-black tracking-wide">
                    <span className="mr-1.5 font-mono font-black text-indigo">{b.barrier_id}</span>
                    {det.name}
                  </span>
                  <span className={`border-2 px-2.5 py-0.5 font-body text-[10px] font-bold tracking-wider ${badge.cls}`}>
                    {badge.label}
                  </span>
                </div>
                <div className="px-4 py-3.5">
                  {det.conditions.map((c, i) => (
                    <div key={i} className="flex items-center gap-2.5 border-b border-sand py-1.5 last:border-b-0">
                      <span className="w-6 text-center">{c.icon}</span>
                      <span className="flex-1 font-body text-sm">{c.text}</span>
                      <span className={`text-[10px] font-bold tracking-wider ${c.met ? 'text-forest' : 'text-brick'}`}>
                        {c.met ? '✓' : 'missing'}
                      </span>
                    </div>
                  ))}
                  <div className="mt-2 h-1 bg-sand">
                    <div className={`h-full ${fillColor}`} style={{ width: `${pct}%` }} />
                  </div>
                  <div className="mt-2 flex items-center gap-1 font-mono text-[11px]">
                    <span className={`border-[1.5px] border-line bg-paper px-2 py-0.5 ${b.status === 'satisfied' ? 'border-forest bg-forest text-white font-bold' : ''}`}>
                      {det.sceneFrom}
                    </span>
                    <span className="text-muted">→</span>
                    <span className={`border-[1.5px] border-line bg-paper px-2 py-0.5 ${b.status === 'satisfied' ? '' : ''}`}>
                      {det.sceneTo}
                    </span>
                  </div>
                </div>
              </div>
            )
          })}
        </div>

        {/* RIGHT: Couplings */}
        <div>
          <div className="relative mb-4 pl-4 text-[10px] font-black uppercase tracking-[3px] text-muted">
            <span className="absolute left-0 top-1/2 h-2 w-2 -translate-y-1/2 rotate-45 bg-primary" />
            Couplings ({couplings.length})
          </div>

          {couplings.map((c) => {
            const det = couplingDetail[c.coupling_id]
            if (!det) return null
            const scoreColor = det.score >= 0.7 ? 'text-primary' : det.score >= 0.3 ? 'text-amber' : 'text-forest'
            const driftPct = Math.min((det.drift / det.threshold) * 100, 100)
            return (
              <div
                key={c.coupling_id}
                className={`mb-3 border-2 border-line bg-white ${det.locked ? '' : ''}`}
                style={c.mode === 'independent' ? { opacity: 0.6 } : undefined}
              >
                <div className="flex items-center justify-between border-b-2 border-line px-4 py-3.5">
                  <span className="text-[13px] font-black tracking-wide">
                    <span className="mr-1.5 font-mono font-black text-indigo">{c.coupling_id}</span>
                    {det.name}
                  </span>
                  <span className={modeTagClass(c.mode)}>{c.mode.toUpperCase()}</span>
                </div>
                <div className="px-4 py-3.5">
                  <div className="mb-3 flex items-center gap-4">
                    <div className={`font-mono text-2xl font-black leading-none ${scoreColor}`}>
                      {det.score.toFixed(2)}
                    </div>
                    <div>
                      <div className="mb-1 text-xs font-bold">
                        {det.score >= 0.7 ? 'High coupling' : det.score >= 0.3 ? 'Medium coupling' : 'Independent'}
                      </div>
                      <div className="font-body text-[10px] text-muted">
                        {det.locked ? 'Barrier B2 not met' : `Shared chars: ${det.sharedChars}`}
                      </div>
                    </div>
                  </div>
                  <div className="flex items-center gap-2">
                    <span className="font-mono text-[10px] text-muted">drift</span>
                    <div className="relative flex-1 h-1.5 bg-sand">
                      <div
                        className="h-full"
                        style={{
                          width: `${driftPct}%`,
                          background: det.locked ? 'var(--sand)' : 'var(--amber)',
                        }}
                      />
                    </div>
                    <span className="font-mono text-[11px] font-bold text-amber-800">
                      +{det.drift} min
                    </span>
                  </div>
                  <div className={`mt-1 font-body text-[10px] ${det.locked ? 'text-muted' : 'text-forest'}`}>
                    {det.locked ? det.note : `✓ Within threshold (${det.threshold}min)`}
                  </div>
                </div>
              </div>
            )
          })}
        </div>
      </div>
    </div>
  )
}

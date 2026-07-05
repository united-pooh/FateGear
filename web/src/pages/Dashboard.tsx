/**
 * Page A: Dashboard
 *
 * Global overview of the current session health: 6 metric cards, latest
 * alerts, scene progress bars, and quick action buttons.
 *
 * Suprematist visual style: bold geometric shapes, warm palette, diamond
 * section-label accents.
 */

import { Link } from 'react-router-dom'
import MetricsCard from '@/components/MetricsCard'
import AlertFeed from '@/components/AlertFeed'
import { useSessionState } from '@/hooks/useSessionState'
import { mockMetrics, mockViolations } from '@/mock/data'

interface MetricDef {
  key: string
  label: string
  icon: string
  getValue: (m: typeof mockMetrics) => string | number
}

const metricsDef: MetricDef[] = [
  { key: 'causal', label: '因果违反', icon: '⏱', getValue: (m) => m.causal_violation_count ?? 0 },
  { key: 'unauth', label: '未授权', icon: '🛡', getValue: (m) => m.unauthorized_action_count ?? 0 },
  { key: 'leak', label: '信息泄露', icon: '💧', getValue: (m) => m.public_payload_leak_count ?? 0 },
  { key: 'spot', label: 'Spot Gap', icon: '◎', getValue: (m) => `${m.spotlight_max_gap_minutes ?? 0}'` },
  { key: 'declass', label: '解密', icon: '⊕', getValue: (m) => (m.declassification_completeness ?? 0).toFixed(2) },
  { key: 'retcon', label: 'Retcon', icon: '↺', getValue: (m) => m.retcon_count ?? 0 },
]

/** Determine ok/warn/error status from metric value */
function getMetricStatus(key: string, value: number): 'ok' | 'warn' | 'error' {
  const thresholds: Record<string, { warn: number; error: number }> = {
    causal: { warn: 1, error: 2 },
    unauth: { warn: 1, error: 2 },
    leak: { warn: 0, error: 1 },
    spot: { warn: 30, error: 45 },
    declass: { warn: 0, error: 0 }, // we invert this: high is good
    retcon: { warn: 1, error: 2 },
  }
  const t = thresholds[key]
  if (!t) return 'ok'
  if (key === 'declass') {
    return value >= 0.8 ? 'ok' : value >= 0.5 ? 'warn' : 'error'
  }
  if (value >= t.error) return 'error'
  if (value >= t.warn) return 'warn'
  return 'ok'
}

interface SceneProgress {
  id: string
  name: string
  committed: number
  total: number
  status: 'active' | 'waiting' | 'locked'
  info: string
}

const sceneProgress: SceneProgress[] = [
  { id: 'hospital_records', name: 'hospital_records', committed: 2, total: 3, status: 'waiting', info: '2/3 events · barrier B2 waiting' },
  { id: 'street', name: 'street', committed: 1, total: 4, status: 'active', info: '1/4 events · active' },
  { id: 'old_house', name: 'old_house', committed: 0, total: 2, status: 'locked', info: '0/2 events · needs B3' },
]

function getStatusColor(status: string): string {
  switch (status) {
    case 'active': return 'bg-forest'
    case 'waiting': return 'bg-gold'
    case 'locked': return 'bg-gray-400 opacity-40'
    default: return 'bg-gray-400'
  }
}

export default function Dashboard() {
  const store = useSessionState()
  const metrics = store.metrics.causal_violation_count !== undefined
    ? store.metrics
    : mockMetrics
  const violations = store.violations.length > 0
    ? store.violations
    : mockViolations

  const minutes = 42
  const eventCount = 8
  const scenesDone = 2
  const scenesTotal = 4

  return (
    <div>
      {/* Header */}
      <header className="mb-9 flex items-start justify-between relative">
        <div>
          <h1 className="text-[28px] font-black tracking-tight leading-tight">警察·医院·老宅</h1>
          <p className="mt-1 font-body text-xs uppercase tracking-[2px] text-muted">KTSL Session Dashboard</p>
          <span className="mt-2 inline-block border border-line bg-paper px-2.5 py-0.5 font-mono text-[11px] text-muted">
            SESS-2026-07-04-A1F3
          </span>
        </div>
        {/* Stats chips */}
        <div className="flex gap-6 items-center">
          <StatChip value={String(minutes)} label="Minutes" />
          <StatChip value={String(eventCount)} label="Events" />
          <StatChip value={`${scenesDone}/${scenesTotal}`} label="Scenes" />
        </div>
        {/* Suprematist accent rectangle */}
        <div className="absolute -top-9 right-16 h-[120px] w-20 rotate-6 bg-primary/12 -z-10" />
      </header>

      {/* Section: Protocol Compliance */}
      <SectionLabel>Protocol Compliance</SectionLabel>
      <div className="mb-10 grid grid-cols-6 gap-3">
        {metricsDef.map((def, i) => {
          const val = def.getValue(metrics)
          const num = typeof val === 'string' ? parseFloat(val.replace("'", '')) : val
          const s = getMetricStatus(def.key, num)
          return (
            <MetricsCard
              key={def.key}
              label={def.label}
              value={val}
              status={s}
              icon={def.icon}
              variant={i as 0 | 1 | 2 | 3 | 4 | 5}
            />
          )
        })}
      </div>

      {/* Section: Recent Alerts */}
      <SectionLabel>Recent Alerts</SectionLabel>
      <div className="mb-10">
        <AlertFeed violations={violations} maxItems={3} />
      </div>

      {/* Section: Quick Actions */}
      <SectionLabel>Quick Actions</SectionLabel>
      <div className="mb-10 grid grid-cols-4 gap-3">
        <QuickAction to="/session" icon="▣" label="提交行动" />
        <QuickAction to="/timeline" icon="≡" label="Timeline" />
        <QuickAction to="/knowledge" icon="⊞" label="知识地图" />
        <QuickAction to="/reports" icon="◉" label="保存状态" />
      </div>

      {/* Section: Scene Progress */}
      <SectionLabel>Scene Progress</SectionLabel>
      <div className="flex flex-col gap-2">
        {sceneProgress.map((scene) => (
          <div
            key={scene.id}
            className="flex items-center gap-4 border-2 border-line bg-white px-5 py-3.5"
          >
            <span className="w-40 shrink-0 text-[13px] font-black tracking-wide">{scene.name}</span>
            <div className="relative h-3.5 flex-1 overflow-hidden border-[1.5px] border-line bg-sand">
              <div
                className={`h-full border-r-2 border-ink ${getStatusColor(scene.status)}`}
                style={{ width: `${(scene.committed / scene.total) * 100}%` }}
              />
            </div>
            <span className="w-64 shrink-0 text-right font-body text-[11px] text-muted">{scene.info}</span>
            {scene.status === 'locked' && (
              <span className="ml-auto text-lg">🔒</span>
            )}
          </div>
        ))}
      </div>
    </div>
  )
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

function StatChip({ value, label }: { value: string; label: string }) {
  return (
    <div className="text-center">
      <div className="text-[22px] font-black leading-none text-indigo">{value}</div>
      <div className="mt-0.5 font-body text-[10px] uppercase tracking-widest text-muted">{label}</div>
    </div>
  )
}

function SectionLabel({ children }: { children: React.ReactNode }) {
  return (
    <div className="relative mb-4 pl-5 text-[10px] font-black uppercase tracking-[4px] text-muted">
      <span className="absolute left-0 top-1/2 h-2.5 w-2.5 -translate-y-1/2 rotate-45 bg-primary" />
      {children}
    </div>
  )
}

function QuickAction({ to, icon, label }: { to: string; icon: string; label: string }) {
  return (
    <Link
      to={to}
      className="border-[2.5px] border-ink bg-white py-5 text-center text-[14px] font-black tracking-wide transition-all hover:-translate-x-0.5 hover:-translate-y-0.5 hover:bg-indigo hover:text-bg hover:shadow-[6px_6px_0_#F59E0B] active:translate-x-0 active:translate-y-0 active:shadow-none"
    >
      <span className="mb-2 block text-[28px]">{icon}</span>
      {label}
    </Link>
  )
}

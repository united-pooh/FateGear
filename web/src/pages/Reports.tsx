/**
 * Page F: Reports
 *
 * Browse, export, and compare historical session reports and publish reports.
 *
 * Suprematist style: tab switcher with ink background, bold table headers,
 * verdict badges (forest/brick), 3-mode × 6-metric comparison table, inline
 * SVG radar chart with three polygons.
 */

import { useState } from 'react'
import RadarChart from '@/components/RadarChart'
import type { MetricSummary, SessionReport } from '@/types/ktsl'
import { mockMetrics, mockReports } from '@/mock/data'

type TabKey = 'session' | 'publish'

const tabs: { key: TabKey; label: string }[] = [
  { key: 'session', label: 'Session Reports' },
  { key: 'publish', label: 'Publish Reports' },
]

function durationOf(report: SessionReport): string {
  const start = new Date(report.started_at).getTime()
  const end = new Date(report.ended_at).getTime()
  return `${Math.round((end - start) / 60000)} min`
}

function statusChip(report: SessionReport): { label: string; cls: string } {
  const violations =
    (report.metrics.causal_violation_count ?? 0) +
    (report.metrics.unauthorized_action_count ?? 0) +
    (report.metrics.public_payload_leak_count ?? 0)
  if (violations === 0 && report.total_blocked === 0) {
    return { label: '✓ CLEAN', cls: 'bg-forest text-white border-forest' }
  }
  if (report.total_blocked > 0) {
    return { label: '✗ ERRORS', cls: 'bg-brick text-white border-red-800' }
  }
  return { label: '⚠ 1 flagged', cls: 'bg-gold text-ink border-amber-700' }
}

export default function Reports() {
  const [activeTab, setActiveTab] = useState<TabKey>('session')
  const [selectedReport, setSelectedReport] = useState(mockReports[0])

  return (
    <div>
      {/* Header */}
      <h1 className="mb-1 text-[22px] font-black">Reports</h1>
      <p className="mb-6 font-body text-[11px] uppercase tracking-[2px] text-muted">
        Session Reports · {mockReports.length} files
      </p>

      {/* Tabs */}
      <div className="flex gap-0 border-b-[3px] border-ink mb-7">
        {tabs.map((tab) => (
          <button
            key={tab.key}
            type="button"
            onClick={() => setActiveTab(tab.key)}
            className={`border-2 border-b-0 border-ink px-6 py-3 text-xs font-black uppercase tracking-wider transition-colors ${
              activeTab === tab.key
                ? 'bg-ink text-bg'
                : 'bg-sand text-ink hover:bg-paper'
            }`}
            style={{ marginBottom: '-3px' }}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {activeTab === 'session' && (
        <SessionReports
          reports={mockReports}
          selected={selectedReport}
          onSelect={setSelectedReport}
        />
      )}
      {activeTab === 'publish' && <PublishReports />}
    </div>
  )
}

function SectionLabel({ children }: { children: React.ReactNode }) {
  return (
    <div className="relative mb-4 pl-4 text-[10px] font-black uppercase tracking-[3px] text-muted">
      <span className="absolute left-0 top-1/2 h-2 w-2 -translate-y-1/2 rotate-45 bg-primary" />
      {children}
    </div>
  )
}

function SessionReports({
  reports,
  selected,
  onSelect,
}: {
  reports: SessionReport[]
  selected: SessionReport
  onSelect: (r: SessionReport) => void
}) {
  return (
    <>
      <SectionLabel>Session Reports List</SectionLabel>

      {/* Report list */}
      <div className="mb-6 border-2 border-ink bg-white">
        {/* Header */}
        <div className="grid grid-cols-[1fr_1fr_80px_80px_100px_120px] gap-0 border-b-2 border-ink bg-paper px-4 py-2.5">
          <div className="text-[10px] font-black uppercase tracking-wider text-muted">Date</div>
          <div className="text-[10px] font-black uppercase tracking-wider text-muted">Module</div>
          <div className="text-[10px] font-black uppercase tracking-wider text-muted">Duration</div>
          <div className="text-[10px] font-black uppercase tracking-wider text-muted">Events</div>
          <div className="text-[10px] font-black uppercase tracking-wider text-muted">Status</div>
          <div />
        </div>
        {/* Rows */}
        {reports.map((r) => {
          const chip = statusChip(r)
          return (
            <button
              key={r.started_at}
              type="button"
              onClick={() => onSelect(r)}
              className={`grid grid-cols-[1fr_1fr_80px_80px_100px_120px] gap-0 border-b-[1.5px] border-line px-4 py-3 text-left transition-colors hover:bg-paper last:border-b-0 ${
                selected.started_at === r.started_at ? 'bg-paper' : ''
              }`}
            >
              <div className="font-mono text-[11px] text-ink">
                {r.started_at.replace('T', ' ').slice(0, 16)}
              </div>
              <div className="text-xs font-bold">{r.fixture_title}</div>
              <div className="font-mono text-[11px] text-muted">{durationOf(r)}</div>
              <div className="font-mono text-[11px] text-muted">{r.total_events}</div>
              <div>
                <span className={`border-2 px-2 py-0.5 text-[10px] font-bold tracking-wider ${chip.cls}`}>
                  {chip.label}
                </span>
              </div>
              <div className="flex gap-1.5">
                <MiniBtn label="MD" />
                <MiniBtn label="HTML" />
                <MiniBtn label="▶" />
              </div>
            </button>
          )
        })}
      </div>

      {/* Preview panel */}
      <div className="grid grid-cols-2 gap-6">
        <div className="border-[3px] border-ink bg-white p-7">
          {/* Verdict badge */}
          <VerdictBadge report={selected} />

          {/* Meta */}
          <div className="mb-5 font-body text-sm leading-relaxed text-muted">
            <strong className="text-ink">Module:</strong> {selected.fixture_title}
            <br />
            <strong className="text-ink">Date:</strong> {selected.started_at.slice(0, 16).replace('T', ' ')} →{' '}
            {selected.ended_at.slice(11, 16)}
            <br />
            <strong className="text-ink">Duration:</strong> {durationOf(selected)} ·{' '}
            {selected.total_events} events committed
            <br />
            <strong className="text-ink">KP:</strong> 田中
          </div>

          {/* 3-mode × 6-metric comparison table */}
          <div className="text-[10px] font-black uppercase tracking-wider text-muted mb-2">
            3-Mode × 6-Metric Comparison
          </div>
          <ModeComparisonTable />
        </div>

        <div className="border-[3px] border-line bg-white p-7 flex flex-col items-center">
          <div className="mb-5 text-[10px] font-black uppercase tracking-[2px] text-muted">
            Metrics Radar
          </div>
          <RadarChart metrics={selected.metrics} compareMetrics={mockMetrics} maxValues={thresholds} />
          <div className="mt-4 flex gap-4 font-body text-[10px] text-muted">
            <span className="flex items-center gap-1">
              <span className="inline-block h-3 w-3 border border-ink bg-forest" />
              KTSL Full
            </span>
            <span className="flex items-center gap-1">
              <span className="inline-block h-3 w-3 border border-ink bg-amber" />
              Schedule
            </span>
            <span className="flex items-center gap-1">
              <span className="inline-block h-3 w-3 border border-ink bg-indigo" />
              Baseline
            </span>
          </div>
        </div>
      </div>
    </>
  )
}

function ModeComparisonTable() {
  return (
    <table className="w-full border-collapse text-[11px]">
      <thead>
        <tr>
          <th className="border-2 border-ink bg-paper px-2.5 py-2 text-center text-[10px] font-black uppercase tracking-wider text-muted">Metric</th>
          <th className="border-2 border-ink bg-sand px-2.5 py-2 text-center text-[10px] font-black uppercase tracking-wider text-muted">Baseline</th>
          <th className="border-2 border-ink bg-sand px-2.5 py-2 text-center text-[10px] font-black uppercase tracking-wider text-muted">Schedule</th>
          <th className="border-2 border-ink bg-paper px-2.5 py-2 text-center text-[10px] font-black uppercase tracking-wider text-muted">KTSL Full</th>
        </tr>
      </thead>
      <tbody>
        <tr>
          <CompCell label="Caus.Vio" baseline="3" schedule="1" ktsl="0" />
        </tr>
        <tr>
          <CompCell label="Unauth" baseline="8" schedule="3" ktsl="0" />
        </tr>
        <tr>
          <CompCell label="Info Leak" baseline="2" schedule="1" ktsl="1" warn />
        </tr>
        <tr>
          <CompCell label="Retcon" baseline="1" schedule="0" ktsl="0" />
        </tr>
        <tr>
          <CompCell label="Spot Gap" baseline="45'" schedule="32'" ktsl="25'" />
        </tr>
        <tr>
          <CompCell label="Declass" baseline=".40" schedule=".65" ktsl=".97" />
        </tr>
      </tbody>
    </table>
  )
}

const thresholds: MetricSummary = {
  causal_violation_count: 2,
  unauthorized_action_count: 2,
  public_payload_leak_count: 1,
  spotlight_max_gap_minutes: 30,
  declassification_completeness: 1.0,
  retcon_count: 2,
}

function PublishReports() {
  return (
    <div className="border-2 border-ink bg-white p-8 text-center">
      <p className="font-body text-sm text-muted mb-4">
        No publish reports available yet. Run a validation to generate one.
      </p>
      <button
        type="button"
        className="border-2 border-ink bg-paper px-6 py-3 text-sm font-black tracking-wide transition-colors hover:bg-indigo hover:text-bg"
      >
        Run Publish Gate →
      </button>
    </div>
  )
}

function MiniBtn({ label }: { label: string }) {
  return (
    <button
      type="button"
      className="border-[1.5px] border-line bg-white px-2.5 py-1 text-[10px] font-bold font-body transition-colors hover:border-indigo hover:text-indigo"
    >
      {label}
    </button>
  )
}

function VerdictBadge({ report }: { report: SessionReport }) {
  const violations =
    (report.metrics.causal_violation_count ?? 0) +
    (report.metrics.unauthorized_action_count ?? 0) +
    (report.metrics.public_payload_leak_count ?? 0)
  const isPass = violations === 0 && report.total_blocked === 0
  return (
    <div
      className={`mb-5 inline-block border-[3px] px-5 py-2 text-[32px] font-black tracking-wider ${
        isPass
          ? 'border-forest bg-forest text-white'
          : 'border-brick bg-brick text-white'
      }`}
    >
      {isPass ? '✓ PASS' : report.total_blocked > 0 ? '✗ FAIL' : '⚠ FLAGGED'}
    </div>
  )
}

function CompCell({
  label,
  baseline,
  schedule,
  ktsl,
  warn = false,
}: {
  label: string
  baseline: string
  schedule: string
  ktsl: string
  warn?: boolean
}) {
  return (
    <tr>
      <td className="border-[1.5px] border-line px-2.5 py-2 text-left font-black">{label}</td>
      <td className="border-[1.5px] border-line px-2.5 py-2 text-center font-mono font-bold">{baseline}</td>
      <td className="border-[1.5px] border-line px-2.5 py-2 text-center font-mono font-bold">{schedule}</td>
      <td className={`border-[1.5px] border-line px-2.5 py-2 text-center font-mono font-bold ${warn ? 'text-brick' : 'text-forest'}`}>
        {ktsl}
      </td>
    </tr>
  )
}

/**
 * Inline SVG radar chart — 6-axis KTSL metrics visualization.
 *
 * Suprematist style: bold polygons in forest/amber/indigo, dashed rings,
 * vertex dots. No external charting library used — pure SVG.
 *
 * Three overlaid polygons represent the three run modes:
 *   — KTSL Full  (large, forest green, solid)
 *   — Schedule-only  (medium, amber, dashed 4/3)
 *   — Baseline  (small, indigo, dashed 2/4)
 */

import type { MetricSummary } from '@/types/ktsl'

export interface MetricsRadarChartProps {
  metrics: MetricSummary
  /** Optional comparison dataset (e.g., previous session) */
  compareMetrics?: MetricSummary
  maxValues?: MetricSummary
}

interface RadarDatum {
  label: string
  value: number
  max: number
}

const SIZE = 320
const CX = SIZE / 2
const CY = SIZE / 2
const RADIUS = 120

const AXIS_KEYS: Array<[keyof MetricSummary, string]> = [
  ['causal_violation_count', 'Causal'],
  ['unauthorized_action_count', 'Unauth'],
  ['public_payload_leak_count', 'Leak'],
  ['spotlight_max_gap_minutes', 'Spot'],
  ['declassification_completeness', 'Decl'],
  ['retcon_count', 'Retcon'],
]

function buildData(metrics: MetricSummary, maxValues?: MetricSummary): RadarDatum[] {
  return AXIS_KEYS.map(([key, label]) => {
    const raw = metrics[key] ?? 0
    // For declass, values are 0–1 scale, normalize to 0–10 for visual
    const value = key === 'declassification_completeness' ? raw * 10 : raw
    const rawMax = maxValues?.[key] ?? 0
    const max = key === 'declassification_completeness' ? rawMax * 10 : rawMax
    return { label, value: Math.min(value, max || 10), max: max || 10 }
  })
}

function polygonPoints(data: RadarDatum[]): string {
  const n = data.length
  return data
    .map((d, i) => {
      const angle = (Math.PI * 2 * i) / n - Math.PI / 2
      const r = d.max > 0 ? (d.value / d.max) * RADIUS : 0
      const x = CX + r * Math.cos(angle)
      const y = CY + r * Math.sin(angle)
      return `${x.toFixed(1)},${y.toFixed(1)}`
    })
    .join(' ')
}

function axisEndpoint(i: number, radius: number): [number, number] {
  const n = AXIS_KEYS.length
  const angle = (Math.PI * 2 * i) / n - Math.PI / 2
  return [CX + radius * Math.cos(angle), CY + radius * Math.sin(angle)]
}

function gridPolygon(r: number): string {
  const n = AXIS_KEYS.length
  return Array.from({ length: n }, (_, i) => {
    const [x, y] = axisEndpoint(i, r)
    return `${x.toFixed(1)},${y.toFixed(1)}`
  }).join(' ')
}

export default function RadarChart({ metrics, compareMetrics, maxValues }: MetricsRadarChartProps) {
  const data = buildData(metrics, maxValues)
  const compareData = compareMetrics ? buildData(compareMetrics, maxValues) : null
  const gridLevels = [0.25, 0.5, 0.75, 1]

  return (
    <svg
      viewBox={`0 0 ${SIZE} ${SIZE}`}
      className="w-full max-w-[360px] mx-auto"
      role="img"
      aria-label="KTSL metrics radar chart"
    >
      {/* Grid rings */}
      {gridLevels.map((level) => (
        <polygon
          key={level}
          points={gridPolygon(RADIUS * level)}
          fill="none"
          stroke="var(--line)"
          strokeWidth={level === 1 ? 2 : 1}
        />
      ))}

      {/* Axis lines */}
      {AXIS_KEYS.map((_, i) => {
        const [ex, ey] = axisEndpoint(i, RADIUS)
        return (
          <line
            key={i}
            x1={CX}
            y1={CY}
            x2={ex}
            y2={ey}
            stroke="var(--line)"
            strokeWidth={1}
          />
        )
      })}

      {/* Max-threshold polygon (amber ring) */}
      <polygon
        points={gridPolygon(RADIUS)}
        fill="var(--amber)"
        fillOpacity={0.1}
        stroke="var(--amber)"
        strokeWidth={2}
        strokeDasharray="6 3"
      />

      {/* Baseline polygon (more violations — smaller shape, indigo) */}
      <polygon
        points={gridPolygon(RADIUS * 0.55)}
        fill="var(--indigo)"
        fillOpacity={0.10}
        stroke="var(--indigo)"
        strokeWidth={2}
        strokeDasharray="2,4"
      />

      {/* Schedule polygon (medium, amber dashed) */}
      {compareData && (
        <polygon
          points={polygonPoints(compareData)}
          fill="var(--amber)"
          fillOpacity={0.12}
          stroke="var(--amber)"
          strokeWidth={2}
          strokeDasharray="4,3"
        />
      )}

      {/* Current KTSL Full polygon (largest — fewest violations) */}
      <polygon
        points={polygonPoints(data)}
        fill="var(--forest)"
        fillOpacity={0.15}
        stroke="var(--forest)"
        strokeWidth={2.5}
      />

      {/* Vertex dots on current polygon */}
      {data.map((d, i) => {
        const angle = (Math.PI * 2 * i) / data.length - Math.PI / 2
        const r = d.max > 0 ? (d.value / d.max) * RADIUS : 0
        const x = CX + r * Math.cos(angle)
        const y = CY + r * Math.sin(angle)
        return (
          <circle key={i} cx={x} cy={y} r={4} fill="var(--forest)" stroke="white" strokeWidth={2} />
        )
      })}

      {/* Center dot */}
      <circle cx={CX} cy={CY} r={3} fill="var(--ink)" />

      {/* Labels */}
      {data.map((d, i) => {
        const [ex, ey] = axisEndpoint(i, RADIUS + 22)
        return (
          <text
            key={i}
            x={ex}
            y={ey}
            textAnchor="middle"
            dominantBaseline="middle"
            fontSize={11}
            fill="var(--ink)"
            fontWeight="bold"
            fontFamily="sans-serif"
          >
            {d.label}
          </text>
        )
      })}
    </svg>
  )
}

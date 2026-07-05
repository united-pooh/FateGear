/**
 * Phase 8 react smoke tests for the KTSL KP web frontend.
 *
 * Renders each page with @testing-library/react to verify the core UI
 * elements are present (metrics cards, submit bar, matrix cells, barrier
 * cards, SVG radar).
 */

import { describe, it, expect } from 'vitest'
import { render, screen } from '@testing-library/react'
import { BrowserRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'

import Dashboard from '@/pages/Dashboard'
import Session from '@/pages/Session'
import KnowledgeMap from '@/pages/KnowledgeMap'
import BarriersCouplings from '@/pages/BarriersCouplings'
import Reports from '@/pages/Reports'

const qc = new QueryClient()

function renderUi(ui: React.ReactElement) {
  return render(
    <QueryClientProvider client={qc}>
      <BrowserRouter>{ui}</BrowserRouter>
    </QueryClientProvider>,
  )
}

describe('Phase 8 Dashboard', () => {
  it('renders 6 metric cards', () => {
    renderUi(<Dashboard />)
    // All metric labels must appear (use getAllByText since some appear multiple times)
    const labels = ['因果违反', '未授权', '信息泄露', 'Spot Gap', '解密', 'Retcon']
    for (const l of labels) {
      expect(screen.getAllByText(l).length).toBeGreaterThanOrEqual(1)
    }
  })

  it('renders session header and quick action buttons', () => {
    renderUi(<Dashboard />)
    // Use header scope to find title
    const heading = screen.getAllByText('警察·医院·老宅')
    expect(heading.length).toBeGreaterThanOrEqual(1)
    // Quick actions
    expect(screen.getAllByText('提交行动').length).toBeGreaterThanOrEqual(1)
    expect(screen.getAllByText('Timeline').length).toBeGreaterThanOrEqual(1)
    expect(screen.getAllByText('知识地图').length).toBeGreaterThanOrEqual(1)
  })
})

describe('Phase 8 Session', () => {
  it('renders event stream and submit bar', () => {
    renderUi(<Session />)
    // Event text
    expect(screen.getByText(/翻找档案柜/)).toBeDefined()
    // Submit bar elements
    expect(screen.getByText('行动描述')).toBeDefined()
    expect(screen.getByText('角色')).toBeDefined()
    expect(screen.getByText('场景')).toBeDefined()
    expect(screen.getByText('提交 →')).toBeDefined()
  })

  it('renders warn event with action buttons', () => {
    renderUi(<Session />)
    // Use getAllByText since there may be multiple warn cards
    expect(screen.getAllByText('OVERRIDE').length).toBeGreaterThanOrEqual(1)
    expect(screen.getAllByText('ROLLBACK').length).toBeGreaterThanOrEqual(1)
    expect(screen.getAllByText('ALLOW+FLAG').length).toBeGreaterThanOrEqual(1)
  })
})

describe('Phase 8 KnowledgeMap', () => {
  it('renders matrix with info_12 leak cell', () => {
    renderUi(<KnowledgeMap />)
    // info_12 appears in the row label
    expect(screen.getAllByText('info_12').length).toBeGreaterThanOrEqual(1)
    // The leak label should appear in the matrix
    expect(screen.getAllByText('泄露').length).toBeGreaterThanOrEqual(1)
    // Row label title
    expect(screen.getAllByText('老宅地下室尸体').length).toBeGreaterThanOrEqual(1)
    // Leak Alert in detail
    expect(screen.getByText('⚠ Leak Alert')).toBeDefined()
  })
})

describe('Phase 8 BarriersCouplings', () => {
  it('renders B2 waiting card and coupling cards', () => {
    renderUi(<BarriersCouplings />)
    // B2 waiting card
    expect(screen.getByText('WAITING')).toBeDefined()
    // C1 coupling card
    expect(screen.getByText('C1')).toBeDefined()
    // Mode tags
    expect(screen.getAllByText('LINKED').length).toBeGreaterThanOrEqual(1)
  })
})

describe('Phase 8 Reports', () => {
  it('renders tab switcher and session report list', () => {
    renderUi(<Reports />)
    expect(screen.getByText('Session Reports')).toBeDefined()
    expect(screen.getByText('Publish Reports')).toBeDefined()
    // Report rows
    expect(screen.getAllByText('police_hospital').length).toBeGreaterThanOrEqual(1)
  })

  it('renders verdict badge and SVG radar chart', () => {
    renderUi(<Reports />)
    // Verdict (first report is flagged)
    expect(screen.getAllByText('⚠ FLAGGED').length).toBeGreaterThanOrEqual(1)
    // SVG radar chart present
    const svg = document.querySelector('svg[aria-label="KTSL metrics radar chart"]')
    expect(svg).not.toBeNull()
  })
})

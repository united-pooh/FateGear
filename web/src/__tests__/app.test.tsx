/**
 * Smoke test placeholder for the KTSL KP web frontend.
 *
 * Phase 7 scaffold: asserts that the project structure is sound.
 * Phase 8 will add proper render tests with @testing-library/react.
 */

import { describe, it, expect } from 'vitest'

describe('KTSL KP Web Scaffold', () => {
  it('has valid type exports', async () => {
    const types = await import('@/types/ktsl')
    // Verify key types are importable (will throw on syntax errors)
    expect(types).toBeDefined()
  })

  it('has valid API client exports', async () => {
    const api = await import('@/api/ktslClient')
    expect(typeof api.validateFixture).toBe('function')
    expect(typeof api.createSession).toBe('function')
    expect(typeof api.submitEvent).toBe('function')
    expect(typeof api.getSessionState).toBe('function')
    expect(typeof api.getTimeline).toBe('function')
    expect(typeof api.getReport).toBe('function')
    expect(typeof api.getKnowledge).toBe('function')
    expect(typeof api.destroySession).toBe('function')
    expect(typeof api.publishFixture).toBe('function')
    expect(typeof api.replaySession).toBe('function')
  })

  it('has valid store exports', async () => {
    const store = await import('@/store/sessionStore')
    expect(typeof store.useSessionStore).toBe('function')
  })

  it('has valid hook exports', async () => {
    const hooks = await import('@/hooks/useSession')
    expect(typeof hooks.useValidateMutation).toBe('function')
    expect(typeof hooks.useCreateSessionMutation).toBe('function')
    expect(typeof hooks.useSubmitEventMutation).toBe('function')
    expect(typeof hooks.useSessionStateQuery).toBe('function')
    expect(typeof hooks.useTimelineQuery).toBe('function')
    expect(typeof hooks.useReportQuery).toBe('function')
    expect(typeof hooks.useKnowledgeQuery).toBe('function')
    expect(typeof hooks.useDestroySessionMutation).toBe('function')
    expect(typeof hooks.usePublishMutation).toBe('function')
    expect(typeof hooks.useReplayMutation).toBe('function')
  })

  it('has valid page component exports', async () => {
    const pages = ['Dashboard', 'Session', 'Timeline', 'KnowledgeMap', 'BarriersCouplings', 'Reports', 'Modules']
    for (const name of pages) {
      const mod = await import(`@/pages/${name}`)
      expect(typeof mod.default).toBe('function')
    }
  })

  it('has valid component exports', async () => {
    const components = [
      'Layout',
      'Sidebar',
      'MetricsCard',
      'EventCard',
      'KnowledgeMatrix',
      'TimelineTrack',
      'RadarChart',
      'AlertFeed',
      'ActionSubmitBar',
    ]
    for (const name of components) {
      const mod = await import(`@/components/${name}`)
      expect(typeof mod.default).toBe('function')
    }
  })
})

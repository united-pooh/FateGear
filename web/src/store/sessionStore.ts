/**
 * Zustand store for the active KTSL session.
 *
 * Holds the in-memory snapshot of the current session: id, fixture, metrics,
 * knowledge map, event log, violations, and current scene. Components read
 * from this store via the `useSessionState` hook; mutations are performed
 * through the action helpers below.
 */

import { create } from 'zustand'
import type {
  AuditEntry,
  EventRecord,
  KnowledgeItem,
  MetricSummary,
  SessionConfig,
  SessionStateSnapshot,
} from '@/types/ktsl'

export interface SessionStore {
  // Identity
  sessionId: string | null
  fixtureId: string | null
  fixtureTitle: string | null

  // Runtime snapshot
  metrics: MetricSummary
  knowledgeMap: Record<string, KnowledgeItem[]>
  eventLog: EventRecord[]
  violations: AuditEntry[]
  currentSceneId: string | null
  config: SessionConfig | null

  // Actions
  setSession: (snapshot: SessionStateSnapshot) => void
  updateMetrics: (metrics: MetricSummary) => void
  setKnowledgeMap: (map: Record<string, KnowledgeItem[]>) => void
  appendEvent: (event: EventRecord) => void
  appendViolation: (violation: AuditEntry) => void
  setCurrentScene: (sceneId: string | null) => void
  reset: () => void
}

const emptyMetrics: MetricSummary = {
  causal_violation_count: 0,
  unauthorized_action_count: 0,
  public_payload_leak_count: 0,
  spotlight_max_gap_minutes: 0,
  declassification_completeness: 0,
  retcon_count: 0,
  high_coupling_time_drift_minutes: 0,
  barrier_wait_minutes: 0,
  committed_event_count: 0,
  blocked_event_count: 0,
}

export const useSessionStore = create<SessionStore>((set) => ({
  sessionId: null,
  fixtureId: null,
  fixtureTitle: null,

  metrics: { ...emptyMetrics },
  knowledgeMap: {},
  eventLog: [],
  violations: [],
  currentSceneId: null,
  config: null,

  setSession: (snapshot) =>
    set({
      sessionId: snapshot.session_id,
      fixtureId: snapshot.fixture_id,
      fixtureTitle: snapshot.fixture_title,
      metrics: snapshot.metrics ?? { ...emptyMetrics },
      knowledgeMap: snapshot.knowledge_map ?? {},
      eventLog: snapshot.event_log ?? [],
      violations: snapshot.violations ?? [],
      currentSceneId: snapshot.current_scene_id ?? null,
      config: snapshot.config ?? null,
    }),

  updateMetrics: (metrics) => set({ metrics }),

  setKnowledgeMap: (map) => set({ knowledgeMap: map }),

  appendEvent: (event) =>
    set((state) => ({ eventLog: [...state.eventLog, event] })),

  appendViolation: (violation) =>
    set((state) => ({ violations: [...state.violations, violation] })),

  setCurrentScene: (sceneId) => set({ currentSceneId: sceneId }),

  reset: () =>
    set({
      sessionId: null,
      fixtureId: null,
      fixtureTitle: null,
      metrics: { ...emptyMetrics },
      knowledgeMap: {},
      eventLog: [],
      violations: [],
      currentSceneId: null,
      config: null,
    }),
}))

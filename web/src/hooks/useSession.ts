/**
 * React Query hooks for the KTSL REST API.
 *
 * Each hook wraps a single endpoint from `ktslClient.ts` and integrates with
 * the QueryClient provider set up in `main.tsx`.
 */

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  createSession,
  destroySession,
  getKnowledge,
  getReport,
  getSessionState,
  getTimeline,
  publishFixture,
  replaySession,
  submitEvent,
  validateFixture,
} from '@/api/ktslClient'
import { useSessionStore } from '@/store/sessionStore'
import type {
  ActionInput,
  KnowledgeItem,
  PublishCriteria,
  SessionStateSnapshot,
} from '@/types/ktsl'

// ---------------------------------------------------------------------------
// Fixture validation
// ---------------------------------------------------------------------------

export function useValidateMutation() {
  return useMutation({
    mutationFn: (fixtureId: string) => validateFixture(fixtureId),
  })
}

// ---------------------------------------------------------------------------
// Session lifecycle
// ---------------------------------------------------------------------------

export function useCreateSessionMutation() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (args: { fixtureId: string; config?: Parameters<typeof createSession>[1] }) =>
      createSession(args.fixtureId, args.config),
    onSuccess: (data) => {
      // Seed the store with the new session id so subsequent queries work.
      qc.invalidateQueries({ queryKey: ['session', data.session_id] })
    },
  })
}

export function useSubmitEventMutation(sessionId: string) {
  const qc = useQueryClient()
  const appendEvent = useSessionStore((s) => s.appendEvent)
  const appendViolation = useSessionStore((s) => s.appendViolation)
  const updateMetrics = useSessionStore((s) => s.updateMetrics)
  return useMutation({
    mutationFn: (input: ActionInput) => submitEvent(sessionId, input),
    onSuccess: (data) => {
      if (data.event_record) appendEvent(data.event_record)
      ;(data.violations ?? []).forEach(appendViolation)
      if (data.updated_metrics) updateMetrics(data.updated_metrics)
      qc.invalidateQueries({ queryKey: ['session', sessionId, 'state'] })
    },
  })
}

export function useSessionStateQuery(sessionId: string | null) {
  return useQuery({
    queryKey: ['session', sessionId, 'state'],
    queryFn: () => getSessionState(sessionId!),
    enabled: !!sessionId,
    refetchInterval: 2_000, // Phase 1: poll every 2s
  })
}

export function useTimelineQuery(sessionId: string | null, sceneId?: string) {
  return useQuery({
    queryKey: ['session', sessionId, 'timeline', sceneId ?? 'all'],
    queryFn: () => getTimeline(sessionId!, sceneId),
    enabled: !!sessionId,
  })
}

export function useReportQuery(
  sessionId: string | null,
  format: 'md' | 'html' = 'md',
) {
  return useQuery({
    queryKey: ['session', sessionId, 'report', format],
    queryFn: () => getReport(sessionId!, format),
    enabled: !!sessionId,
  })
}

export function useKnowledgeQuery(sessionId: string | null, characterId?: string) {
  return useQuery({
    queryKey: ['session', sessionId, 'knowledge', characterId ?? 'all'],
    queryFn: (): Promise<Record<string, KnowledgeItem[]>> =>
      getKnowledge(sessionId!, characterId),
    enabled: !!sessionId,
  })
}

export function useDestroySessionMutation() {
  const reset = useSessionStore((s) => s.reset)
  return useMutation({
    mutationFn: (sessionId: string) => destroySession(sessionId),
    onSuccess: () => reset(),
  })
}

// ---------------------------------------------------------------------------
// Publish gate
// ---------------------------------------------------------------------------

export function usePublishMutation() {
  return useMutation({
    mutationFn: (args: { fixtureId: string; criteria?: PublishCriteria }) =>
      publishFixture(args.fixtureId, args.criteria),
  })
}

// ---------------------------------------------------------------------------
// Replay
// ---------------------------------------------------------------------------

export function useReplayMutation() {
  return useMutation({
    mutationFn: (stateJson: SessionStateSnapshot) => replaySession(stateJson),
  })
}

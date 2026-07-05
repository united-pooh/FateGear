/**
 * Convenience hook that reads from the Zustand session store.
 *
 * Components that need the current session snapshot (metrics, event log,
 * violations, etc.) should use this hook rather than accessing the store
 * directly — it keeps the API surface consistent with the React Query hooks
 * in `useSession.ts`.
 */

import { useSessionStore } from '@/store/sessionStore'
import type { SessionStore } from '@/store/sessionStore'

export function useSessionState(): SessionStore {
  return useSessionStore()
}

export function useCurrentMetrics() {
  return useSessionStore((s) => s.metrics)
}

export function useEventLog() {
  return useSessionStore((s) => s.eventLog)
}

export function useViolations() {
  return useSessionStore((s) => s.violations)
}

export function useKnowledgeMap() {
  return useSessionStore((s) => s.knowledgeMap)
}

export function useCurrentScene() {
  return useSessionStore((s) => s.currentSceneId)
}

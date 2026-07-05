/**
 * fetch wrapper for the KTSL KP toolchain REST API.
 *
 * All endpoints are proxied through Vite dev server at /ktsl → http://localhost:8080.
 */

import type {
  ActionInput,
  AuditResult,
  CreateSessionRequest,
  KnowledgeItem,
  PublishGateResult,
  PublishRequest,
  ReplayRequest,
  SessionConfig,
  SessionReport,
  SessionStateSnapshot,
  ValidateReport,
  PublishCriteria,
} from '@/types/ktsl'

const BASE = '/ktsl'

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${BASE}${path}`, {
    headers: { 'Content-Type': 'application/json' },
    ...init,
  })
  if (!res.ok) {
    throw new Error(`KTSL API error ${res.status}: ${await res.text()}`)
  }
  return res.json() as Promise<T>
}

// ---------------------------------------------------------------------------
// Fixture validation
// ---------------------------------------------------------------------------

export function validateFixture(fixtureId: string): Promise<ValidateReport> {
  return request<ValidateReport>('/validate', {
    method: 'POST',
    body: JSON.stringify({ fixture_id: fixtureId }),
  })
}

// ---------------------------------------------------------------------------
// Session lifecycle
// ---------------------------------------------------------------------------

export function createSession(
  fixtureId: string,
  config?: SessionConfig,
): Promise<{ session_id: string }> {
  const body: CreateSessionRequest = { fixture_id: fixtureId, config }
  return request<{ session_id: string }>('/session', {
    method: 'POST',
    body: JSON.stringify(body),
  })
}

export function submitEvent(
  sessionId: string,
  input: ActionInput,
): Promise<AuditResult> {
  return request<AuditResult>(`/session/${sessionId}/events`, {
    method: 'POST',
    body: JSON.stringify(input),
  })
}

export function getSessionState(sessionId: string): Promise<SessionStateSnapshot> {
  return request<SessionStateSnapshot>(`/session/${sessionId}/state`)
}

export function getTimeline(
  sessionId: string,
  sceneId?: string,
): Promise<{ scene_id: string; events: SessionStateSnapshot[] }> {
  const qs = sceneId ? `?scene_id=${encodeURIComponent(sceneId)}` : ''
  return request(`/session/${sessionId}/timeline${qs}`)
}

export function getReport(
  sessionId: string,
  format: 'md' | 'html' = 'md',
): Promise<{ format: string; content: string }> {
  return request(`/session/${sessionId}/report?format=${format}`)
}

export function getKnowledge(
  sessionId: string,
  characterId?: string,
): Promise<Record<string, KnowledgeItem[]>> {
  const qs = characterId ? `?character_id=${encodeURIComponent(characterId)}` : ''
  return request(`/session/${sessionId}/knowledge${qs}`)
}

export function destroySession(sessionId: string): Promise<{ ok: true }> {
  return request(`/session/${sessionId}`, { method: 'DELETE' })
}

// ---------------------------------------------------------------------------
// Publish gate
// ---------------------------------------------------------------------------

export function publishFixture(
  fixtureId: string,
  criteria?: PublishCriteria,
): Promise<PublishGateResult> {
  const body: PublishRequest = { fixture_id: fixtureId, criteria }
  return request<PublishGateResult>('/publish', {
    method: 'POST',
    body: JSON.stringify(body),
  })
}

// ---------------------------------------------------------------------------
// Replay
// ---------------------------------------------------------------------------

export function replaySession(stateJson: SessionStateSnapshot): Promise<{
  session_id: string
  report: SessionReport
}> {
  const body: ReplayRequest = { state_json: stateJson }
  return request('/replay', {
    method: 'POST',
    body: JSON.stringify(body),
  })
}

/**
 * TypeScript type definitions for the KTSL KP toolchain.
 *
 * These types mirror the Pydantic models defined in:
 *   - src/scenario/ktsl/models.py
 *   - src/scenario/report/session_reports.py
 *
 * Single source of truth is the Python models; this file is a manual
 * translation kept in sync by hand.
 */

// ---------------------------------------------------------------------------
// Primitives / Literals
// ---------------------------------------------------------------------------

export type RunMode = 'baseline' | 'schedule_only' | 'ktsl_full'

export type InfoKind = 'know' | 'obs'

export type SensitivityLevel = 'public' | 'low' | 'medium' | 'high' | 'keeper'

export type Visibility = 'public' | 'private' | 'keeper'

export type CommitStatus = 'proposed' | 'committed' | 'blocked' | 'retconned'

export type BarrierStatus = 'open' | 'waiting' | 'satisfied' | 'blocked'

export type CouplingMode = 'independent' | 'loose' | 'linked' | 'locked'

export type ConditionType =
  | 'none'
  | 'required_info'
  | 'required_scene'
  | 'causal_dependency'
  | 'shared_character'
  | 'time_barrier'

export type DecisionStatus = 'allowed' | 'blocked' | 'redacted' | 'declassified'

export type AuditMetric =
  | 'causal_violation'
  | 'unauthorized_action'
  | 'public_payload_leak'
  | 'spotlight_gap'
  | 'declassification'
  | 'retcon'
  | 'coupling_drift'

// ---------------------------------------------------------------------------
// Domain models (Layer 1)
// ---------------------------------------------------------------------------

export interface KTSLLocation {
  id: string
  name: string
  public_summary?: string
  keeper_summary?: string
  tags?: string[]
}

export interface KeeperTruth {
  id: string
  scene_id: string
  payload: string
  linked_info_ids?: string[]
  sensitivity?: SensitivityLevel
}

export interface InfoLabel {
  id: string
  kind: InfoKind
  scene_id: string
  payload: string
  sensitivity?: SensitivityLevel
  public_payload?: string
  redaction?: string
  source_event_id?: string
  source_scene_id?: string
  observed_by_player_ids?: string[]
  known_by_character_ids?: string[]
  authorized_character_ids?: string[]
  declassified_for_character_ids?: string[]
  expected_declassified_for_character_ids?: string[]
  is_declassified?: boolean
  should_declassify?: boolean
  notes?: string
}

export interface ClueRecord {
  id: string
  scene_id: string
  info_id: string
  title: string
  public_hint?: string
  keeper_detail?: string
  required_info_ids?: string[]
  output_info_ids?: string[]
  is_settleable?: boolean
}

export interface BarrierCheckpoint {
  id: string
  scene_ids?: string[]
  required_event_ids?: string[]
  required_info_ids?: string[]
  status?: BarrierStatus
  reason?: string
  waiting_event_ids?: string[]
  waiting_cost_minutes?: number
  committed_event_ids?: string[]
}

export interface SceneCard {
  id: string
  name: string
  location_id: string
  participant_character_ids?: string[]
  participant_player_ids?: string[]
  public_summary?: string
  keeper_summary?: string
  info_ids?: string[]
  clue_ids?: string[]
  keeper_truth_ids?: string[]
  barrier_id?: string
  has_commit_boundary?: boolean
  time_start_minute?: number
  time_end_minute?: number
  spotlight_start_minute?: number
  spotlight_end_minute?: number
  coupling_input_ids?: string[]
  tags?: string[]
}

export interface CausalDependency {
  id: string
  required_event_ids?: string[]
  required_info_ids?: string[]
  reason?: string
}

export interface EventRecord {
  id: string
  scene_id: string
  action_id: string
  action_text: string
  actor?: string
  player_id?: string
  character_id?: string
  is_settleable?: boolean
  visibility?: Visibility
  status?: CommitStatus
  committed?: boolean
  commit_index?: number | null
  barrier_id?: string
  required_info_ids?: string[]
  observed_info_ids?: string[]
  known_info_ids?: string[]
  output_info_ids?: string[]
  causal_dependency_ids?: string[]
  depends_on_event_ids?: string[]
  public_payload?: string
  private_payload?: string
  redaction?: string
  time_start_minute?: number
  time_end_minute?: number
  spotlight_start_minute?: number
  spotlight_end_minute?: number
  notes?: string
}

export interface CommitRecord {
  id: string
  event_id: string
  scene_id: string
  status?: CommitStatus
  commit_index?: number | null
  barrier_id?: string
  actor?: string
  reason?: string
}

export interface ActorKnowledgeState {
  player_id?: string
  character_id: string
  scene_id?: string
  observed_info_ids?: string[]
  known_info_ids?: string[]
  authorized_info_ids?: string[]
  notes?: string
}

export interface SceneCoupling {
  id: string
  source_scene_id: string
  target_scene_id: string
  coupling_score?: number
  mode?: CouplingMode
  condition_type?: ConditionType
  required_info_ids?: string[]
  required_scene_ids?: string[]
  input_event_ids?: string[]
  output_info_ids?: string[]
  shared_character_ids?: string[]
  barrier_id?: string
  barrier_policy?: 'none' | 'soft' | 'hard'
  expected_drift_minutes?: number
  rationale?: string
}

export interface ScheduleStep {
  id: string
  run_mode: RunMode
  scene_id: string
  event_id: string
  actor?: string
  status?: CommitStatus
  commit_index?: number | null
  barrier_id?: string
  wait_reason?: string
  wait_cost_minutes?: number
  depends_on_event_ids?: string[]
  required_info_ids?: string[]
  output_info_ids?: string[]
  missing_event_ids?: string[]
  missing_info_ids?: string[]
  time_start_minute?: number
  time_end_minute?: number
  spotlight_start_minute?: number
  spotlight_end_minute?: number
  sort_key?: [number, string]
}

export interface FilterDecision {
  id: string
  run_mode: RunMode
  info_id: string
  event_id?: string
  player_id?: string
  character_id?: string
  status: DecisionStatus
  authorized?: boolean
  declassified?: boolean
  leaked_public_payload?: boolean
  public_payload?: string
  redaction?: string
  reason_code?: string
  reason?: string
}

export interface CouplingDecision {
  id: string
  run_mode: RunMode
  coupling_id: string
  status: DecisionStatus
  condition_type?: ConditionType
  coupling_score?: number
  barrier_required?: boolean
  barrier_id?: string
  required_info_ids?: string[]
  required_scene_ids?: string[]
  input_event_ids?: string[]
  output_info_ids?: string[]
  unmet_required_info_ids?: string[]
  unmet_required_scene_ids?: string[]
  unmet_input_event_ids?: string[]
  drift_minutes?: number
  reason?: string
}

export interface AuditEntry {
  id: string
  metric: AuditMetric
  run_mode: RunMode
  scene_id?: string
  event_id?: string
  info_id?: string
  player_id?: string
  character_id?: string
  severity?: 'info' | 'warning' | 'error'
  message: string
  caused_by_event_ids?: string[]
  caused_by_info_ids?: string[]
}

export interface MetricSummary {
  causal_violation_count?: number
  unauthorized_action_count?: number
  public_payload_leak_count?: number
  spotlight_max_gap_minutes?: number
  declassification_completeness?: number
  retcon_count?: number
  high_coupling_time_drift_minutes?: number
  barrier_wait_minutes?: number
  committed_event_count?: number
  blocked_event_count?: number
}

export interface EvaluationResult {
  fixture_id: string
  run_mode: RunMode
  metrics?: MetricSummary
  schedule_steps?: ScheduleStep[]
  filter_decisions?: FilterDecision[]
  coupling_decisions?: CouplingDecision[]
  audit_entries?: AuditEntry[]
  simulated_data_notice?: string
  metadata?: Record<string, unknown>
}

export interface KTSLFixture {
  id: string
  title: string
  description?: string
  run_modes?: RunMode[]
  locations?: KTSLLocation[]
  scenes?: SceneCard[]
  keeper_truths?: KeeperTruth[]
  info_labels?: InfoLabel[]
  clues?: ClueRecord[]
  initial_knowledge?: ActorKnowledgeState[]
  causal_dependencies?: CausalDependency[]
  events?: EventRecord[]
  commit_records?: CommitRecord[]
  barriers?: BarrierCheckpoint[]
  couplings?: SceneCoupling[]
  expected_declassified_info_ids?: string[]
  simulation_notice?: string
  seed_label?: string
  metadata?: Record<string, unknown>
}

// ---------------------------------------------------------------------------
// Layer 4 orchestration models
// ---------------------------------------------------------------------------

export interface AuditResult {
  allowed: boolean
  resolution: 'matched' | 'keyword_fallback' | 'manual' | 'unresolved'
  event_record?: EventRecord | null
  violations?: AuditEntry[]
  warnings?: string[]
  updated_metrics?: MetricSummary | null
  matched_clue_id?: string | null
}

export interface SessionConfig {
  session_id?: string
  fixture_id: string
  started_at?: string
  kp_name?: string
  default_visibility?: Visibility
  allow_override?: boolean
  notes?: string
}

export interface KnowledgeItem {
  info_id: string
  kind: InfoKind
  sensitivity: SensitivityLevel
  content_summary: string
  source_event_id: string
  source_scene_id: string
  acquired_at_minute?: number
}

export interface ActionParseResult {
  resolution: 'matched' | 'keyword_fallback' | 'unresolved'
  event_record?: EventRecord | null
  matched_clue_id?: string | null
  score?: number
  candidate_clues?: Array<[string, number]>
}

export interface ManualOverrides {
  output_info_ids?: string[]
  required_info_ids?: string[]
  barrier_id?: string
  causal_dependency_ids?: string[]
  depends_on_event_ids?: string[]
}

export interface SessionSummary {
  fixture_id: string
  fixture_title: string
  started_at: string
  total_events: number
  total_committed: number
  total_overridden: number
}

export interface BarrierState {
  barrier_id: string
  status: BarrierStatus
  required_event_ids?: string[]
  satisfied_event_ids?: string[]
  required_info_ids?: string[]
  satisfied_info_ids?: string[]
}

export interface CouplingState {
  coupling_id: string
  source_scene_id: string
  target_scene_id: string
  mode: CouplingMode
  drift_minutes?: number
  active?: boolean
}

export interface ModeThresholds {
  max_causal_violations?: number | null
  max_unauthorized_actions?: number | null
  max_public_payload_leaks?: number | null
  max_spotlight_gap_minutes?: number | null
  min_declassification_completeness?: number | null
  max_retcons?: number | null
  max_high_coupling_drift_minutes?: number | null
}

export interface PublishCriteria {
  version?: string
  fixture_id?: string
  description?: string
  thresholds?: Partial<Record<RunMode, ModeThresholds>>
}

export interface ModeResult {
  mode: RunMode
  passed: boolean
  metrics: MetricSummary
  failures?: string[]
  warnings?: string[]
}

export interface PublishGateResult {
  overall_pass: boolean
  per_mode: ModeResult[]
  evaluated_at: string
  fixture_id: string
  criteria_version: string
}

// ---------------------------------------------------------------------------
// Layer 3 — Report view models
// ---------------------------------------------------------------------------

export interface ViolationEvent {
  event_id: string
  event_index: number
  actor: string
  action_text: string
  scene_id: string
  severity: 'info' | 'warning' | 'error'
  metric: AuditMetric
  message: string
  overridden?: boolean
}

export interface EventSummary {
  event_id: string
  event_index: number
  actor: string
  action_text: string
  time_minute?: number
  output_info_ids?: string[]
  status?: CommitStatus
}

export interface KnowledgeItemView {
  info_id: string
  kind: InfoKind
  sensitivity: SensitivityLevel
  content_summary: string
  source_event_id: string
  source_scene_id: string
  acquired_at_minute?: number
  leaked?: boolean
}

export interface SceneTimelineView {
  scene_id: string
  scene_name?: string
  events?: EventSummary[]
  total_events?: number
  committed_events?: number
}

export interface BarrierStateView {
  barrier_id: string
  status: BarrierStatus
  required_event_ids?: string[]
  satisfied_event_ids?: string[]
  required_info_ids?: string[]
  satisfied_info_ids?: string[]
}

export interface CouplingStateView {
  coupling_id: string
  source_scene_id: string
  target_scene_id: string
  mode: CouplingMode
  drift_minutes?: number
  active?: boolean
}

export interface SessionReport {
  fixture_id: string
  fixture_title: string
  started_at: string
  ended_at: string
  session_config?: SessionConfig | null
  total_events: number
  total_committed: number
  total_blocked: number
  total_overridden: number
  metrics: MetricSummary
  violation_timeline?: ViolationEvent[]
  final_knowledge_map?: Record<string, KnowledgeItemView[]>
  scene_timelines?: Record<string, EventSummary[]>
  barrier_final_states?: BarrierStateView[]
  coupling_final_states?: CouplingStateView[]
}

export interface PublishReport {
  fixture_id: string
  fixture_title: string
  evaluated_at: string
  criteria_version: string
  overall_pass: boolean
  per_mode: ModeResult[]
  thresholds?: Partial<Record<RunMode, ModeThresholds>>
}

export interface ValidateIssue {
  level: 'error' | 'warning' | 'info'
  code: string
  message: string
  resource_id?: string
}

export interface ValidateReport {
  fixture_id: string
  fixture_title?: string
  validated_at?: string
  is_valid: boolean
  issues?: ValidateIssue[]
}

export interface ModuleStaticCheck {
  fixture_id: string
  checks_passed: boolean
  errors?: string[]
  warnings?: string[]
}

// ---------------------------------------------------------------------------
// Layer 4 — Session state snapshot (GET /session/{id}/state)
// ---------------------------------------------------------------------------

export interface SessionStateSnapshot {
  session_id: string
  fixture_id: string
  fixture_title: string
  current_scene_id?: string | null
  metrics: MetricSummary
  event_log?: EventRecord[]
  violations?: AuditEntry[]
  knowledge_map?: Record<string, KnowledgeItem[]>
  barrier_states?: BarrierState[]
  coupling_states?: CouplingState[]
  config?: SessionConfig | null
}

// ---------------------------------------------------------------------------
// Layer 5 — Request DTOs
// ---------------------------------------------------------------------------

export interface ActionInput {
  action: string
  actor: string
  scene_id: string
  visibility?: Visibility
  manual_overrides?: ManualOverrides
}

export interface CreateSessionRequest {
  fixture_id: string
  config?: SessionConfig
}

export interface PublishRequest {
  fixture_id: string
  criteria?: PublishCriteria
}

export interface ReplayRequest {
  state_json: SessionStateSnapshot
}
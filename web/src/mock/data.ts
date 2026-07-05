/**
 * Static mock data for Phase 8 UI rendering.
 *
 * Used as fallback when the backend API is unreachable. Mirrors the shape
 * of the API responses defined in `src/types/ktsl.ts`.
 */

import type {
  AuditEntry,
  BarrierState,
  CouplingState,
  EventRecord,
  KnowledgeItemView,
  MetricSummary,
  SessionReport,
  SessionStateSnapshot,
} from '@/types/ktsl'

// ---------------------------------------------------------------------------
// Mock snapshot
// ---------------------------------------------------------------------------

export const mockMetrics: MetricSummary = {
  causal_violation_count: 0,
  unauthorized_action_count: 1,
  public_payload_leak_count: 0,
  spotlight_max_gap_minutes: 25,
  declassification_completeness: 0.97,
  retcon_count: 0,
  high_coupling_time_drift_minutes: 5,
  barrier_wait_minutes: 12,
  committed_event_count: 8,
  blocked_event_count: 0,
}

export const mockEvents: EventRecord[] = [
  {
    id: 'E001',
    scene_id: 'hospital_records',
    action_id: 'a_001',
    action_text: '翻找档案柜里的人事记录',
    actor: '佐藤',
    character_id: 'char_satou',
    visibility: 'public',
    status: 'committed',
    committed: true,
    commit_index: 1,
    output_info_ids: ['info_07'],
    time_start_minute: 0,
    time_end_minute: 5,
  },
  {
    id: 'E002',
    scene_id: 'street',
    action_id: 'a_002',
    action_text: '跟踪下班的医生来到街角',
    actor: '李',
    character_id: 'char_lee',
    visibility: 'public',
    status: 'committed',
    committed: true,
    commit_index: 2,
    output_info_ids: ['info_09'],
    time_start_minute: 6,
    time_end_minute: 12,
  },
  {
    id: 'E003',
    scene_id: 'street',
    action_id: 'a_003',
    action_text: '躲在暗处偷听佐藤和医生的对话',
    actor: '李',
    character_id: 'char_lee',
    visibility: 'public',
    status: 'committed',
    committed: true,
    commit_index: 3,
    output_info_ids: ['info_07_summary'],
    observed_info_ids: ['info_12_hint'],
    time_start_minute: 14,
    time_end_minute: 22,
  },
  {
    id: 'E004',
    scene_id: 'hospital_records',
    action_id: 'a_004',
    action_text: '追问医生关于深夜值班名单的事情',
    actor: '佐藤',
    character_id: 'char_satou',
    visibility: 'public',
    status: 'committed',
    committed: true,
    commit_index: 4,
    barrier_id: 'B1',
    time_start_minute: 24,
    time_end_minute: 30,
  },
  {
    id: 'E005',
    scene_id: 'street',
    action_id: 'a_005',
    action_text: '向王描述医生可疑的举动',
    actor: '李',
    character_id: 'char_lee',
    visibility: 'public',
    status: 'committed',
    committed: true,
    commit_index: 5,
    output_info_ids: ['info_09'],
    time_start_minute: 32,
    time_end_minute: 38,
  },
  {
    id: 'E006',
    scene_id: 'street',
    action_id: 'a_006',
    action_text: '王决定去老宅查看',
    actor: '王',
    character_id: 'char_wang',
    visibility: 'public',
    status: 'committed',
    committed: true,
    commit_index: 6,
    time_start_minute: 39,
    time_end_minute: 42,
  },
]

export const mockViolations: AuditEntry[] = [
  {
    id: 'V001',
    metric: 'unauthorized_action',
    run_mode: 'ktsl_full',
    scene_id: 'street',
    event_id: 'E003',
    character_id: 'char_lee',
    severity: 'warning',
    message: '潜在信息泄露 — 李可能推断出 info_12（高敏感）',
    caused_by_event_ids: ['E007'],
  },
]

export const mockKnowledgeMap: Record<string, KnowledgeItemView[]> = {
  '佐藤': [
    { info_id: 'info_01', kind: 'know', sensitivity: 'public', content_summary: '警察搜查令', source_event_id: 'init', source_scene_id: 'hospital_records' },
    { info_id: 'info_07', kind: 'know', sensitivity: 'low', content_summary: '档案记录内容', source_event_id: 'E001', source_scene_id: 'hospital_records', acquired_at_minute: 5 },
    { info_id: 'info_12', kind: 'know', sensitivity: 'high', content_summary: '老宅地下室有一具尸体', source_event_id: 'E005', source_scene_id: 'old_house', acquired_at_minute: 38 },
    { info_id: 'info_15', kind: 'know', sensitivity: 'keeper', content_summary: '真凶身份', source_event_id: 'init', source_scene_id: null as unknown as string },
    { info_id: 'info_09', kind: 'obs', sensitivity: 'medium', content_summary: '医生深夜行踪', source_event_id: 'E006', source_scene_id: 'street', acquired_at_minute: 42 },
  ],
  '李': [
    { info_id: 'info_01', kind: 'know', sensitivity: 'public', content_summary: '警察搜查令', source_event_id: 'init', source_scene_id: 'hospital_records' },
    { info_id: 'info_07', kind: 'obs', sensitivity: 'low', content_summary: '佐藤在找某物（摘要）', source_event_id: 'E003', source_scene_id: 'street', acquired_at_minute: 22 },
    { info_id: 'info_12', kind: 'obs', sensitivity: 'high', content_summary: '老宅地下室有一具尸体', source_event_id: 'E007', source_scene_id: 'street', acquired_at_minute: 30, leaked: true },
    { info_id: 'info_09', kind: 'know', sensitivity: 'medium', content_summary: '医生深夜行踪', source_event_id: 'E002', source_scene_id: 'street', acquired_at_minute: 12 },
  ],
  '王': [
    { info_id: 'info_01', kind: 'know', sensitivity: 'public', content_summary: '警察搜查令', source_event_id: 'init', source_scene_id: 'hospital_records' },
    { info_id: 'info_07', kind: 'obs', sensitivity: 'low', content_summary: '档案记录摘要', source_event_id: 'E001', source_scene_id: 'hospital_records', acquired_at_minute: 10 },
    { info_id: 'info_09', kind: 'know', sensitivity: 'medium', content_summary: '医生深夜行踪', source_event_id: 'E005', source_scene_id: 'street', acquired_at_minute: 38 },
  ],
  'NPC_医生': [
    { info_id: 'info_01', kind: 'know', sensitivity: 'public', content_summary: '警察搜查令', source_event_id: 'init', source_scene_id: 'hospital_records' },
    { info_id: 'info_07', kind: 'know', sensitivity: 'low', content_summary: '档案记录（医生本人记录）', source_event_id: 'init', source_scene_id: 'hospital_records' },
    { info_id: 'info_09', kind: 'obs', sensitivity: 'medium', content_summary: '医生深夜行踪（自己）', source_event_id: 'E002', source_scene_id: 'street', acquired_at_minute: 12 },
    { info_id: 'info_12', kind: 'know', sensitivity: 'high', content_summary: '老宅地下室有一具尸体', source_event_id: 'init', source_scene_id: null as unknown as string },
  ],
}

export const mockBarrierStates: BarrierState[] = [
  {
    barrier_id: 'B1',
    status: 'satisfied',
    required_event_ids: ['E001', 'E004'],
    satisfied_event_ids: ['E001', 'E004'],
  },
  {
    barrier_id: 'B2',
    status: 'waiting',
    required_event_ids: ['E008'],
    satisfied_event_ids: [],
  },
  {
    barrier_id: 'B3',
    status: 'blocked',
    required_info_ids: ['info_07'],
    satisfied_info_ids: [],
  },
]

export const mockCouplingStates: CouplingState[] = [
  {
    coupling_id: 'C1',
    source_scene_id: 'hospital_records',
    target_scene_id: 'street',
    mode: 'linked',
    drift_minutes: 5,
    active: true,
  },
  {
    coupling_id: 'C2',
    source_scene_id: 'street',
    target_scene_id: 'old_house',
    mode: 'loose',
    drift_minutes: 0,
    active: false,
  },
  {
    coupling_id: 'C3',
    source_scene_id: 'hospital_wing',
    target_scene_id: 'hospital_records',
    mode: 'independent',
    drift_minutes: 0,
    active: false,
  },
]

export const mockSessionSnapshot: SessionStateSnapshot = {
  session_id: 'SESS-2026-07-04-A1F3',
  fixture_id: 'police_hospital_old_house',
  fixture_title: '警察·医院·老宅',
  current_scene_id: 'street',
  metrics: mockMetrics,
  event_log: mockEvents,
  violations: mockViolations,
  knowledge_map: mockKnowledgeMap as unknown as Record<string, import('@/types/ktsl').KnowledgeItem[]>,
  barrier_states: mockBarrierStates,
  coupling_states: mockCouplingStates,
}

// ---------------------------------------------------------------------------
// Mock reports
// ---------------------------------------------------------------------------

export const mockReports: SessionReport[] = [
  {
    fixture_id: 'police_hospital_old_house',
    fixture_title: 'police_hospital',
    started_at: '2026-07-04T14:22:00',
    ended_at: '2026-07-04T15:04:00',
    total_events: 8,
    total_committed: 8,
    total_blocked: 0,
    total_overridden: 1,
    metrics: mockMetrics,
  },
  {
    fixture_id: 'police_hospital_old_house',
    fixture_title: 'police_hospital',
    started_at: '2026-07-03T20:05:00',
    ended_at: '2026-07-03T21:03:00',
    total_events: 12,
    total_committed: 12,
    total_blocked: 0,
    total_overridden: 0,
    metrics: { ...mockMetrics, unauthorized_action_count: 0 },
  },
  {
    fixture_id: 'simple_library',
    fixture_title: 'simple_library',
    started_at: '2026-06-28T19:30:00',
    ended_at: '2026-06-28T20:05:00',
    total_events: 5,
    total_committed: 3,
    total_blocked: 2,
    total_overridden: 0,
    metrics: {
      ...mockMetrics,
      causal_violation_count: 2,
      unauthorized_action_count: 3,
      spotlight_max_gap_minutes: 45,
      declassification_completeness: 0.4,
    },
  },
]

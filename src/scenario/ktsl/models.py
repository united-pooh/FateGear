"""KTSL deterministic domain contracts.

These models describe the paper-style Schedule, Filter, and Coupling slice as
serializable fixture data. They intentionally do not depend on SceneRuntime,
views, NPC orchestration, network services, or LLM output.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator


RunMode = Literal["baseline", "schedule_only", "ktsl_full"]
InfoKind = Literal["know", "obs"]
SensitivityLevel = Literal["public", "low", "medium", "high", "keeper"]
Visibility = Literal["public", "private", "keeper"]
CommitStatus = Literal["proposed", "committed", "blocked", "retconned"]
BarrierStatus = Literal["open", "waiting", "satisfied", "blocked"]
CouplingMode = Literal["independent", "loose", "linked", "locked"]
ConditionType = Literal[
    "none",
    "required_info",
    "required_scene",
    "causal_dependency",
    "shared_character",
    "time_barrier",
]
DecisionStatus = Literal["allowed", "blocked", "redacted", "declassified"]
AuditMetric = Literal[
    "causal_violation",
    "unauthorized_action",
    "public_payload_leak",
    "spotlight_gap",
    "declassification",
    "retcon",
    "coupling_drift",
]


def default_run_modes() -> list[RunMode]:
    return ["baseline", "schedule_only", "ktsl_full"]


class KTSLLocation(BaseModel):
    id: str = Field(..., min_length=1, max_length=60)
    name: str = Field(..., min_length=1, max_length=120)
    public_summary: str = Field(default="", max_length=1000)
    keeper_summary: str = Field(default="", max_length=1500)
    tags: list[str] = Field(default_factory=list)


class KeeperTruth(BaseModel):
    id: str = Field(..., min_length=1, max_length=80)
    scene_id: str = Field(..., min_length=1, max_length=60)
    payload: str = Field(..., min_length=1, max_length=2000)
    linked_info_ids: list[str] = Field(default_factory=list)
    sensitivity: SensitivityLevel = "keeper"


class InfoLabel(BaseModel):
    id: str = Field(..., min_length=1, max_length=80)
    kind: InfoKind
    scene_id: str = Field(..., min_length=1, max_length=60)
    payload: str = Field(..., min_length=1, max_length=2000)
    sensitivity: SensitivityLevel = "public"
    public_payload: str = Field(default="", max_length=1200)
    redaction: str = Field(default="", max_length=1200)
    source_event_id: str = Field(default="", max_length=80)
    source_scene_id: str = Field(default="", max_length=60)
    observed_by_player_ids: list[str] = Field(default_factory=list)
    known_by_character_ids: list[str] = Field(default_factory=list)
    authorized_character_ids: list[str] = Field(default_factory=list)
    declassified_for_character_ids: list[str] = Field(default_factory=list)
    expected_declassified_for_character_ids: list[str] = Field(default_factory=list)
    is_declassified: bool = False
    should_declassify: bool = False
    notes: str = Field(default="", max_length=1000)


class ClueRecord(BaseModel):
    id: str = Field(..., min_length=1, max_length=80)
    scene_id: str = Field(..., min_length=1, max_length=60)
    info_id: str = Field(..., min_length=1, max_length=80)
    title: str = Field(..., min_length=1, max_length=120)
    public_hint: str = Field(default="", max_length=800)
    keeper_detail: str = Field(default="", max_length=1200)
    required_info_ids: list[str] = Field(default_factory=list)
    output_info_ids: list[str] = Field(default_factory=list)
    is_settleable: bool = True


class BarrierCheckpoint(BaseModel):
    id: str = Field(..., min_length=1, max_length=80)
    scene_ids: list[str] = Field(default_factory=list)
    required_event_ids: list[str] = Field(default_factory=list)
    required_info_ids: list[str] = Field(default_factory=list)
    status: BarrierStatus = "open"
    reason: str = Field(default="", max_length=1000)
    waiting_event_ids: list[str] = Field(default_factory=list)
    waiting_cost_minutes: int = Field(default=0, ge=0)
    committed_event_ids: list[str] = Field(default_factory=list)


class SceneCard(BaseModel):
    id: str = Field(..., min_length=1, max_length=60)
    name: str = Field(..., min_length=1, max_length=120)
    location_id: str = Field(..., min_length=1, max_length=60)
    participant_character_ids: list[str] = Field(default_factory=list)
    participant_player_ids: list[str] = Field(default_factory=list)
    public_summary: str = Field(default="", max_length=1000)
    keeper_summary: str = Field(default="", max_length=1500)
    info_ids: list[str] = Field(default_factory=list)
    clue_ids: list[str] = Field(default_factory=list)
    keeper_truth_ids: list[str] = Field(default_factory=list)
    barrier_id: str = Field(default="", max_length=80)
    has_commit_boundary: bool = True
    time_start_minute: int = Field(default=0, ge=0)
    time_end_minute: int = Field(default=0, ge=0)
    spotlight_start_minute: int = Field(default=0, ge=0)
    spotlight_end_minute: int = Field(default=0, ge=0)
    coupling_input_ids: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)


class CausalDependency(BaseModel):
    id: str = Field(..., min_length=1, max_length=80)
    required_event_ids: list[str] = Field(default_factory=list)
    required_info_ids: list[str] = Field(default_factory=list)
    reason: str = Field(default="", max_length=1000)


class EventRecord(BaseModel):
    id: str = Field(..., min_length=1, max_length=80)
    scene_id: str = Field(..., min_length=1, max_length=60)
    action_id: str = Field(..., min_length=1, max_length=80)
    action_text: str = Field(..., min_length=1, max_length=1000)
    actor: str = Field(default="", max_length=80)
    player_id: str = Field(default="", max_length=80)
    character_id: str = Field(default="", max_length=80)
    is_settleable: bool = True
    visibility: Visibility = "public"
    status: CommitStatus = "proposed"
    committed: bool = False
    commit_index: int | None = Field(default=None, ge=0)
    barrier_id: str = Field(default="", max_length=80)
    required_info_ids: list[str] = Field(default_factory=list)
    observed_info_ids: list[str] = Field(default_factory=list)
    known_info_ids: list[str] = Field(default_factory=list)
    output_info_ids: list[str] = Field(default_factory=list)
    causal_dependency_ids: list[str] = Field(default_factory=list)
    depends_on_event_ids: list[str] = Field(default_factory=list)
    public_payload: str = Field(default="", max_length=1200)
    private_payload: str = Field(default="", max_length=2000)
    redaction: str = Field(default="", max_length=1200)
    time_start_minute: int = Field(default=0, ge=0)
    time_end_minute: int = Field(default=0, ge=0)
    spotlight_start_minute: int = Field(default=0, ge=0)
    spotlight_end_minute: int = Field(default=0, ge=0)
    notes: str = Field(default="", max_length=1000)


class CommitRecord(BaseModel):
    id: str = Field(..., min_length=1, max_length=80)
    event_id: str = Field(..., min_length=1, max_length=80)
    scene_id: str = Field(..., min_length=1, max_length=60)
    status: CommitStatus = "proposed"
    commit_index: int | None = Field(default=None, ge=0)
    barrier_id: str = Field(default="", max_length=80)
    actor: str = Field(default="", max_length=80)
    reason: str = Field(default="", max_length=1000)


class ActorKnowledgeState(BaseModel):
    player_id: str = Field(default="", max_length=80)
    character_id: str = Field(..., min_length=1, max_length=80)
    scene_id: str = Field(default="", max_length=60)
    observed_info_ids: list[str] = Field(default_factory=list)
    known_info_ids: list[str] = Field(default_factory=list)
    authorized_info_ids: list[str] = Field(default_factory=list)
    notes: str = Field(default="", max_length=1000)


class SceneCoupling(BaseModel):
    id: str = Field(..., min_length=1, max_length=80)
    source_scene_id: str = Field(..., min_length=1, max_length=60)
    target_scene_id: str = Field(..., min_length=1, max_length=60)
    coupling_score: float = Field(default=0.0, ge=0.0, le=1.0)
    mode: CouplingMode = "independent"
    condition_type: ConditionType = "none"
    required_info_ids: list[str] = Field(default_factory=list)
    required_scene_ids: list[str] = Field(default_factory=list)
    input_event_ids: list[str] = Field(default_factory=list)
    output_info_ids: list[str] = Field(default_factory=list)
    shared_character_ids: list[str] = Field(default_factory=list)
    barrier_id: str = Field(default="", max_length=80)
    barrier_policy: Literal["none", "soft", "hard"] = "none"
    expected_drift_minutes: int = Field(default=0, ge=0)
    rationale: str = Field(default="", max_length=1000)


class ScheduleStep(BaseModel):
    id: str = Field(..., min_length=1, max_length=80)
    run_mode: RunMode
    scene_id: str = Field(..., min_length=1, max_length=60)
    event_id: str = Field(..., min_length=1, max_length=80)
    actor: str = Field(default="", max_length=80)
    status: CommitStatus = "proposed"
    commit_index: int | None = Field(default=None, ge=0)
    barrier_id: str = Field(default="", max_length=80)
    wait_reason: str = Field(default="", max_length=1000)
    wait_cost_minutes: int = Field(default=0, ge=0)
    depends_on_event_ids: list[str] = Field(default_factory=list)
    required_info_ids: list[str] = Field(default_factory=list)
    output_info_ids: list[str] = Field(default_factory=list)
    missing_event_ids: list[str] = Field(default_factory=list)
    missing_info_ids: list[str] = Field(default_factory=list)
    time_start_minute: int = Field(default=0, ge=0)
    time_end_minute: int = Field(default=0, ge=0)
    spotlight_start_minute: int = Field(default=0, ge=0)
    spotlight_end_minute: int = Field(default=0, ge=0)
    sort_key: tuple[int, str] = Field(default=(0, ""))


class FilterDecision(BaseModel):
    id: str = Field(..., min_length=1, max_length=80)
    run_mode: RunMode
    info_id: str = Field(..., min_length=1, max_length=80)
    event_id: str = Field(default="", max_length=80)
    player_id: str = Field(default="", max_length=80)
    character_id: str = Field(default="", max_length=80)
    status: DecisionStatus
    authorized: bool = False
    declassified: bool = False
    leaked_public_payload: bool = False
    public_payload: str = Field(default="", max_length=1200)
    redaction: str = Field(default="", max_length=1200)
    reason_code: str = Field(default="", max_length=120)
    reason: str = Field(default="", max_length=1000)


class CouplingDecision(BaseModel):
    id: str = Field(..., min_length=1, max_length=80)
    run_mode: RunMode
    coupling_id: str = Field(..., min_length=1, max_length=80)
    status: DecisionStatus
    condition_type: ConditionType = "none"
    coupling_score: float = Field(default=0.0, ge=0.0, le=1.0)
    barrier_required: bool = False
    barrier_id: str = Field(default="", max_length=80)
    required_info_ids: list[str] = Field(default_factory=list)
    required_scene_ids: list[str] = Field(default_factory=list)
    input_event_ids: list[str] = Field(default_factory=list)
    output_info_ids: list[str] = Field(default_factory=list)
    unmet_required_info_ids: list[str] = Field(default_factory=list)
    unmet_required_scene_ids: list[str] = Field(default_factory=list)
    unmet_input_event_ids: list[str] = Field(default_factory=list)
    drift_minutes: int = Field(default=0, ge=0)
    reason: str = Field(default="", max_length=1000)


class AuditEntry(BaseModel):
    id: str = Field(..., min_length=1, max_length=80)
    metric: AuditMetric
    run_mode: RunMode
    scene_id: str = Field(default="", max_length=60)
    event_id: str = Field(default="", max_length=80)
    info_id: str = Field(default="", max_length=80)
    player_id: str = Field(default="", max_length=80)
    character_id: str = Field(default="", max_length=80)
    severity: Literal["info", "warning", "error"] = "info"
    message: str = Field(..., min_length=1, max_length=1000)
    caused_by_event_ids: list[str] = Field(default_factory=list)
    caused_by_info_ids: list[str] = Field(default_factory=list)


class MetricSummary(BaseModel):
    causal_violation_count: int = Field(default=0, ge=0)
    unauthorized_action_count: int = Field(default=0, ge=0)
    public_payload_leak_count: int = Field(default=0, ge=0)
    spotlight_max_gap_minutes: int = Field(default=0, ge=0)
    declassification_completeness: float = Field(default=0.0, ge=0.0, le=1.0)
    retcon_count: int = Field(default=0, ge=0)
    high_coupling_time_drift_minutes: int = Field(default=0, ge=0)
    barrier_wait_minutes: int = Field(default=0, ge=0)
    committed_event_count: int = Field(default=0, ge=0)
    blocked_event_count: int = Field(default=0, ge=0)


class EvaluationResult(BaseModel):
    fixture_id: str = Field(..., min_length=1, max_length=80)
    run_mode: RunMode
    metrics: MetricSummary = Field(default_factory=MetricSummary)
    schedule_steps: list[ScheduleStep] = Field(default_factory=list)
    filter_decisions: list[FilterDecision] = Field(default_factory=list)
    coupling_decisions: list[CouplingDecision] = Field(default_factory=list)
    audit_entries: list[AuditEntry] = Field(default_factory=list)
    simulated_data_notice: str = Field(
        default="Results are generated from deterministic simulated fixtures, not real play evidence.",
        max_length=300,
    )
    metadata: dict[str, Any] = Field(default_factory=dict)


class KTSLFixture(BaseModel):
    id: str = Field(..., min_length=1, max_length=80)
    title: str = Field(..., min_length=1, max_length=160)
    description: str = Field(default="", max_length=2000)
    run_modes: list[RunMode] = Field(default_factory=default_run_modes)
    locations: list[KTSLLocation] = Field(default_factory=list)
    scenes: list[SceneCard] = Field(default_factory=list)
    keeper_truths: list[KeeperTruth] = Field(default_factory=list)
    info_labels: list[InfoLabel] = Field(default_factory=list)
    clues: list[ClueRecord] = Field(default_factory=list)
    initial_knowledge: list[ActorKnowledgeState] = Field(default_factory=list)
    causal_dependencies: list[CausalDependency] = Field(default_factory=list)
    events: list[EventRecord] = Field(default_factory=list)
    commit_records: list[CommitRecord] = Field(default_factory=list)
    barriers: list[BarrierCheckpoint] = Field(default_factory=list)
    couplings: list[SceneCoupling] = Field(default_factory=list)
    expected_declassified_info_ids: list[str] = Field(default_factory=list)
    simulation_notice: str = Field(
        default="This fixture is deterministic simulated research data, not a real empirical play transcript.",
        max_length=300,
    )
    seed_label: str = Field(default="deterministic", max_length=80)
    metadata: dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Layer 4 orchestration models (Phase 1 + Phase 2)
# ---------------------------------------------------------------------------


class AuditResult(BaseModel):
    """Single submit_action return value."""

    allowed: bool
    resolution: Literal["matched", "keyword_fallback", "manual", "unresolved"]
    event_record: EventRecord | None = None
    violations: list[AuditEntry] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    updated_metrics: MetricSummary | None = None
    matched_clue_id: str | None = None


class SessionConfig(BaseModel):
    """Session-level configuration declared at session start."""

    session_id: str = Field(default="", max_length=80)
    fixture_id: str
    started_at: str = ""
    kp_name: str = Field(default="", max_length=60)
    default_visibility: Visibility = "public"
    allow_override: bool = True
    notes: str = Field(default="", max_length=2000)


class KnowledgeItem(BaseModel):
    """One entry in a character's knowledge map."""

    info_id: str
    kind: InfoKind
    sensitivity: SensitivityLevel
    content_summary: str
    source_event_id: str
    source_scene_id: str
    acquired_at_minute: int = 0


class ActionParseResult(BaseModel):
    """Return value of RuntimeEventAdapter.parse_action()."""

    resolution: Literal["matched", "keyword_fallback", "unresolved"]
    event_record: EventRecord | None = None
    matched_clue_id: str | None = None
    score: float = 0.0
    candidate_clues: list[tuple[str, float]] = Field(default_factory=list)


class ManualOverrides(BaseModel):
    """When auto-resolve fails, KP manually specifies info flow."""

    output_info_ids: list[str] = Field(default_factory=list)
    required_info_ids: list[str] = Field(default_factory=list)
    barrier_id: str = ""
    causal_dependency_ids: list[str] = Field(default_factory=list)
    depends_on_event_ids: list[str] = Field(default_factory=list)


class SessionSummary(BaseModel):
    """Compact session overview used when generating reports."""

    fixture_id: str
    fixture_title: str
    started_at: str
    total_events: int
    total_committed: int
    total_overridden: int


class BarrierState(BaseModel):
    """Final state of a barrier."""

    barrier_id: str
    status: BarrierStatus
    required_event_ids: list[str] = Field(default_factory=list)
    satisfied_event_ids: list[str] = Field(default_factory=list)
    required_info_ids: list[str] = Field(default_factory=list)
    satisfied_info_ids: list[str] = Field(default_factory=list)


class CouplingState(BaseModel):
    """Final state of a coupling."""

    coupling_id: str
    source_scene_id: str
    target_scene_id: str
    mode: CouplingMode
    drift_minutes: int = 0
    active: bool = True


class ModeThresholds(BaseModel):
    """Thresholds for a single run mode (publish gate)."""

    max_causal_violations: int | None = None
    max_unauthorized_actions: int | None = None
    max_public_payload_leaks: int | None = None
    max_spotlight_gap_minutes: int | None = None
    min_declassification_completeness: float | None = None
    max_retcons: int | None = None
    max_high_coupling_drift_minutes: int | None = None


class PublishCriteria(BaseModel):
    """Publish gate threshold configuration."""

    version: str = "1.0.0"
    fixture_id: str = ""
    description: str = Field(default="", max_length=1000)
    thresholds: dict[RunMode, ModeThresholds] = Field(default_factory=dict)


class ModeResult(BaseModel):
    """Single-mode publish gate simulation result."""

    mode: RunMode
    passed: bool
    metrics: MetricSummary
    failures: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class PublishGateResult(BaseModel):
    """Overall publish gate verdict."""

    overall_pass: bool
    per_mode: list[ModeResult]
    evaluated_at: str
    fixture_id: str
    criteria_version: str


# ---------------------------------------------------------------------------
# Milestone 1: Runtime Ledger
# ---------------------------------------------------------------------------


class KTSLOverrideRecord(BaseModel):
    """Immutable record of a KP override on a blocked intervention."""

    id: str = Field(..., min_length=1, max_length=80)
    intervention_id: str = Field(..., min_length=1, max_length=80)
    override_type: Literal["force_allow", "force_block", "declassify"]
    reason: str = Field(..., min_length=1, max_length=600)
    kp_name: str = Field(default="", max_length=60)
    created_at: str = Field(default="")


class KTSLPromptTemplateSet(BaseModel):
    """Bundle of prompt template overrides for a session."""

    broadcast_narration: str = Field(default="", max_length=2000)
    private_note: str = Field(default="", max_length=2000)
    redaction_notice: str = Field(default="", max_length=2000)
    grayzone_guidance: str = Field(default="", max_length=2000)


class ModuleSceneKTSLSpec(BaseModel):
    scene_id: str = Field(..., min_length=1, max_length=60)
    initial_mode: CouplingMode = "independent"
    participant_character_ids: list[str] = Field(default_factory=list)
    participant_player_ids: list[str] = Field(default_factory=list)
    time_start_minute: int = Field(default=0, ge=0)
    time_end_minute: int = Field(default=0, ge=0)
    spotlight_start_minute: int = Field(default=0, ge=0)
    spotlight_end_minute: int = Field(default=0, ge=0)
    tags: list[str] = Field(default_factory=list)


class ModuleInfoLabelSpec(BaseModel):
    info_id: str = Field(..., min_length=1, max_length=80)
    payload: str = Field(..., min_length=1, max_length=2000)
    sensitivity: SensitivityLevel = "public"
    public_payload: str = Field(default="", max_length=1200)
    redaction: str = Field(default="", max_length=1200)
    known_by_character_ids: list[str] = Field(default_factory=list)
    authorized_character_ids: list[str] = Field(default_factory=list)
    declassification_condition: str = Field(default="", max_length=500)


class ModuleBarrierSpec(BaseModel):
    id: str = Field(..., min_length=1, max_length=80)
    scene_ids: list[str] = Field(default_factory=list)
    required_event_ids: list[str] = Field(default_factory=list)
    required_info_ids: list[str] = Field(default_factory=list)
    status: BarrierStatus = "open"
    reason: str = Field(default="", max_length=1000)


class ModuleCouplingSpec(BaseModel):
    source_scene_id: str
    target_scene_id: str
    condition_type: ConditionType = "none"
    required_info_ids: list[str] = Field(default_factory=list)
    required_scene_ids: list[str] = Field(default_factory=list)
    barrier_policy: Literal["none", "soft", "hard"] = "none"
    rationale: str = Field(default="", max_length=600)


class ModuleInitialKnowledgeSpec(BaseModel):
    character_id: str = Field(..., min_length=1, max_length=60)
    known_info_ids: list[str] = Field(default_factory=list)
    observed_info_ids: list[str] = Field(default_factory=list)
    authorized_info_ids: list[str] = Field(default_factory=list)


class ModuleKTSLSpec(BaseModel):
    """Optional ktsl_spec block in a module.yaml, consumed by WizardStage."""

    scenes: list[ModuleSceneKTSLSpec] = Field(default_factory=list)
    info_labels: list[ModuleInfoLabelSpec] = Field(default_factory=list)
    couplings: list[ModuleCouplingSpec] = Field(default_factory=list)
    barriers: list[ModuleBarrierSpec] = Field(default_factory=list)
    initial_knowledge: list[ModuleInitialKnowledgeSpec] = Field(default_factory=list)

    @model_validator(mode="after")
    def _validate_coupling_refs(self) -> "ModuleKTSLSpec":
        scene_ids = {s.scene_id for s in self.scenes}
        for coupling in self.couplings:
            if coupling.source_scene_id not in scene_ids:
                raise ValueError(
                    f"coupling source_scene_id {coupling.source_scene_id!r} "
                    f"not in scenes"
                )
            if coupling.target_scene_id not in scene_ids:
                raise ValueError(
                    f"coupling target_scene_id {coupling.target_scene_id!r} "
                    f"not in scenes"
                )
            for info_id in coupling.required_info_ids:
                if not any(il.info_id == info_id for il in self.info_labels):
                    raise ValueError(
                        f"coupling required_info_id {info_id!r} not in info_labels"
                    )
        return self


class KTSLLedger(BaseModel):
    """First-class ledger living inside SessionMapState."""

    module_id: str = Field(..., min_length=1, max_length=30)
    scenes: dict[str, SceneCard] = Field(default_factory=dict)
    events: list[EventRecord] = Field(default_factory=list)
    info_labels: dict[str, InfoLabel] = Field(default_factory=dict)
    couplings: list[SceneCoupling] = Field(default_factory=list)
    knowledge: dict[str, ActorKnowledgeState] = Field(default_factory=dict)
    barriers: list[BarrierCheckpoint] = Field(default_factory=list)
    overrides: list[KTSLOverrideRecord] = Field(default_factory=list)
    narration_rules: KTSLPromptTemplateSet = Field(
        default_factory=KTSLPromptTemplateSet
    )

    @classmethod
    def empty(cls, module_id: str) -> "KTSLLedger":
        return cls(module_id=module_id)

    @classmethod
    def from_module_spec(
        cls,
        module_id: str,
        spec: ModuleKTSLSpec,
    ) -> "KTSLLedger":
        barriers = [
            BarrierCheckpoint(
                id=b.id,
                scene_ids=list(b.scene_ids),
                required_event_ids=list(b.required_event_ids),
                required_info_ids=list(b.required_info_ids),
                status=b.status,
                reason=b.reason,
            )
            for b in spec.barriers
        ]
        scenes = {
            s.scene_id: SceneCard(
                id=s.scene_id,
                name=s.scene_id,
                location_id=s.scene_id,
                participant_character_ids=list(s.participant_character_ids),
                participant_player_ids=list(s.participant_player_ids),
                time_start_minute=s.time_start_minute,
                time_end_minute=s.time_end_minute,
                spotlight_start_minute=s.spotlight_start_minute,
                spotlight_end_minute=s.spotlight_end_minute,
                tags=list(s.tags),
            )
            for s in spec.scenes
        }
        info_labels = {
            info.info_id: InfoLabel(
                id=info.info_id,
                kind="know",
                scene_id=info.info_id,
                payload=info.payload,
                sensitivity=info.sensitivity,
                public_payload=info.public_payload,
                redaction=info.redaction,
                known_by_character_ids=list(info.known_by_character_ids),
                authorized_character_ids=list(info.authorized_character_ids),
            )
            for info in spec.info_labels
        }
        couplings = [
            SceneCoupling(
                id=f"coupling_{c.source_scene_id}_{c.target_scene_id}",
                source_scene_id=c.source_scene_id,
                target_scene_id=c.target_scene_id,
                condition_type=c.condition_type,
                required_info_ids=list(c.required_info_ids),
                required_scene_ids=list(c.required_scene_ids),
                barrier_policy=c.barrier_policy,
                rationale=c.rationale,
            )
            for c in spec.couplings
        ]
        knowledge = {
            k.character_id: ActorKnowledgeState(
                character_id=k.character_id,
                known_info_ids=list(k.known_info_ids),
                observed_info_ids=list(k.observed_info_ids),
                authorized_info_ids=list(k.authorized_info_ids),
            )
            for k in spec.initial_knowledge
        }
        return cls(
            module_id=module_id,
            scenes=scenes,
            info_labels=info_labels,
            couplings=couplings,
            barriers=barriers,
            knowledge=knowledge,
        )

    def snapshot(self) -> dict[str, object]:
        return {
            "module_id": self.module_id,
            "scene_ids": sorted(self.scenes),
            "committed_count": sum(1 for e in self.events if e.committed),
            "pending_count": sum(1 for e in self.events if not e.committed),
            "info_count": len(self.info_labels),
            "coupling_count": len(self.couplings),
            "override_count": len(self.overrides),
        }

    def commit_event(self, event: EventRecord) -> None:
        """Append and mark committed."""
        event.committed = True
        event.status = "committed"
        self.events.append(event)

    def apply_override(self, record: KTSLOverrideRecord) -> None:
        self.overrides.append(record)


__all__ = [
    "KTSLOverrideRecord",
    "KTSLPromptTemplateSet",
    "ModuleSceneKTSLSpec",
    "ModuleInfoLabelSpec",
    "ModuleCouplingSpec",
    "ModuleInitialKnowledgeSpec",
    "ModuleKTSLSpec",
    "KTSLLedger",
]

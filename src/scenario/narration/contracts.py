"""Narration-stage contracts.

The narration package is a render-stage layer. Its models may preserve public
prose continuity, tone, and NPC presentation, but they do not own StoryState,
scene location, flags, clocks, endings, completed actions, pending intents, or
check results. Those authoritative facts remain owned by the runtime.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from scenario.runtime.contracts import RuntimeEvent


JsonMap = dict[str, Any]


class NarrationEventRef(BaseModel):
    """Stable narration-only reference for a committed RuntimeEvent."""

    event_id: str = Field(..., min_length=1)
    session_id: str = Field(..., min_length=1, max_length=30)
    turn_no: int = Field(..., ge=1)
    event_index: int = Field(..., ge=0)
    event_type: str = Field(..., min_length=1)
    event_hash: str = Field(..., min_length=8, max_length=64)
    log_line: str = Field(default="")
    runtime_event: RuntimeEvent


class NarrativeState(BaseModel):
    """Public narration continuity only; never authoritative game state."""

    model_config = ConfigDict(validate_assignment=True, extra="forbid")

    scene_mood: dict[str, str] = Field(
        default_factory=dict,
        description="Public mood/tone notes keyed by scene id.",
    )
    npc_attitudes: dict[str, dict[str, str]] = Field(
        default_factory=dict,
        description=(
            "Public NPC attitude notes keyed by NPC id, then by player id. "
            'The default bucket uses player_id="*" for backward compatibility.'
        ),
    )
    clue_emphasis: dict[str, str] = Field(
        default_factory=dict,
        description="Public clue presentation notes keyed by clue id.",
    )
    public_observations: dict[str, str] = Field(
        default_factory=dict,
        description="Public sensory or continuity observations keyed by topic.",
    )
    continuity_notes: list[str] = Field(
        default_factory=list,
        description="Short public continuity notes for future narration.",
    )
    style_tags: list[str] = Field(
        default_factory=list,
        description="Presentation style tags such as tense, pacing, or tone.",
    )


class NarrationPatchProposal(BaseModel):
    """A model-proposed MVU patch against NarrativeState only."""

    path: str = Field(
        ...,
        min_length=1,
        description=(
            "Dot path under allowed NarrativeState public fields. Authoritative "
            "runtime paths such as story_state, scene_instances, player_states, "
            "global_flags, clock_values, completed_actions, endings, and check "
            "results are forbidden."
        ),
    )
    old_value: Any = Field(..., description="Current NarrativeState value.")
    new_value: Any = Field(..., description="Proposed NarrativeState value.")
    reason: str = Field(..., min_length=1, max_length=500)
    source_event_ids: list[str] = Field(default_factory=list)
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    scope: str = Field(default="public", description="First version supports public only.")


class RejectedPatchAudit(BaseModel):
    path: str
    reason: str
    proposal: NarrationPatchProposal


class PatchApplicationResult(BaseModel):
    state: NarrativeState
    accepted_patches: list[NarrationPatchProposal] = Field(default_factory=list)
    rejected_patches: list[RejectedPatchAudit] = Field(default_factory=list)


class SceneSnapshot(BaseModel):
    scene_id: str
    scene_name: str = ""
    is_cleared: bool = False
    has_event_occurred: bool = False
    completed_action_ids: list[str] = Field(default_factory=list)
    local_flags: list[str] = Field(default_factory=list)


class PlayerSceneSnapshot(BaseModel):
    player_id: str
    current_scene_id: str
    current_scene_name: str = ""
    last_scene_id: str = ""


class StorySnapshot(BaseModel):
    current_stage_id: str
    stage_name: str = ""
    stage_description: str = ""
    stage_entered_turn: int = Field(default=1, ge=1)
    resolved_ending_id: str | None = None


class RuleFact(BaseModel):
    kind: str
    text: str
    data: JsonMap = Field(default_factory=dict)


class StateDiff(BaseModel):
    kind: str
    path: str
    old_value: Any = None
    new_value: Any = None
    source_event_ids: list[str] = Field(default_factory=list)


class CheckResultFact(BaseModel):
    event_id: str
    player_id: str = ""
    scene_id: str = ""
    action_id: str = ""
    action_name: str = ""
    success: bool
    reason: str = ""
    effects_applied: list[str] = Field(default_factory=list)


class StaticSceneContext(BaseModel):
    scene_id: str
    scene_name: str
    description: str = ""
    tags: list[str] = Field(default_factory=list)


class NarrationInputPacket(BaseModel):
    """Committed input available to the render-stage Keeper agent."""

    session_id: str
    turn_no: int = Field(..., ge=1)
    module_id: str
    module_title: str = ""
    event_refs: list[NarrationEventRef] = Field(default_factory=list)
    player_scene_snapshots: list[PlayerSceneSnapshot] = Field(default_factory=list)
    scene_snapshots: list[SceneSnapshot] = Field(default_factory=list)
    story_snapshot: StorySnapshot
    rule_facts: list[RuleFact] = Field(default_factory=list)
    state_diffs: list[StateDiff] = Field(default_factory=list)
    check_results: list[CheckResultFact] = Field(default_factory=list)
    forbidden_facts: list[str] = Field(default_factory=list)
    narrative_state: NarrativeState = Field(default_factory=NarrativeState)
    recent_record_summary: str = ""
    static_scene_context: list[StaticSceneContext] = Field(default_factory=list)
    retrieved_memory_ids: list[str] = Field(default_factory=list)

    @property
    def event_ids(self) -> set[str]:
        return {event_ref.event_id for event_ref in self.event_refs}


class VectorMemoryMetadata(BaseModel):
    memory_id: str = Field(..., min_length=1)
    source_turn: int = Field(..., ge=1)
    source_event_ids: list[str] = Field(default_factory=list)
    session_id: str = ""
    module_id: str = ""
    scope: str = Field(default="public")
    kind: Literal["narrative", "npc", "scene", "clue"]
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    source_text: str = ""
    source_record_id: str = ""
    created_from: Literal["seed", "record", "patch"] = "seed"
    status: Literal["active", "stale", "forgotten"] = "active"
    created_at: str = ""
    updated_at: str = ""
    valid_from_turn: int | None = Field(default=None, ge=1)
    valid_to_turn: int | None = Field(default=None, ge=1)
    supersedes: list[str] = Field(default_factory=list)
    tags: list[str] = Field(default_factory=list)
    forget_reason: str = ""


class VectorMemory(BaseModel):
    metadata: VectorMemoryMetadata
    summary_text: str = Field(..., min_length=1)

    @property
    def memory_id(self) -> str:
        return self.metadata.memory_id


class PromptLayerSummary(BaseModel):
    name: str
    required: bool
    char_count: int = Field(..., ge=0)
    omitted: bool = False


class PromptBuildResult(BaseModel):
    prompt: str
    layers: list[PromptLayerSummary] = Field(default_factory=list)
    omitted_layers: list[str] = Field(default_factory=list)
    max_chars: int | None = None


class NpcLine(BaseModel):
    speaker_id: str = Field(..., min_length=1, max_length=80)
    text: str = Field(..., min_length=1, max_length=1000)


class KeeperNarrationDraft(BaseModel):
    public_text: str = Field(..., min_length=1)
    npc_lines: list[NpcLine] = Field(default_factory=list)
    keeper_notes: list[str] = Field(default_factory=list)
    patch_proposals: list[NarrationPatchProposal] = Field(default_factory=list)
    source_event_ids: list[str] = Field(default_factory=list)
    cited_memory_ids: list[str] = Field(default_factory=list)
    style_notes: list[str] = Field(default_factory=list)

    @field_validator("source_event_ids", "cited_memory_ids")
    @classmethod
    def _deduplicate_ids(cls, value: list[str]) -> list[str]:
        return list(dict.fromkeys(value))


class ModelMetadata(BaseModel):
    provider: str = ""
    model: str = ""
    response_id: str = ""
    latency_ms: int | None = Field(default=None, ge=0)
    prompt_tokens: int | None = Field(default=None, ge=0)
    completion_tokens: int | None = Field(default=None, ge=0)


class NarrationValidationResult(BaseModel):
    final_draft: KeeperNarrationDraft
    accepted_patches: list[NarrationPatchProposal] = Field(default_factory=list)
    rejected_patches: list[RejectedPatchAudit] = Field(default_factory=list)
    updated_state: NarrativeState = Field(default_factory=NarrativeState)
    fallback_used: bool = False
    fallback_reasons: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class KeeperNarrationRecord(BaseModel):
    record_id: str
    session_id: str
    turn_no: int = Field(..., ge=1)
    final_public_text: str
    npc_lines: list[NpcLine] = Field(default_factory=list)
    keeper_notes: list[str] = Field(default_factory=list)
    accepted_patches: list[NarrationPatchProposal] = Field(default_factory=list)
    rejected_patches: list[RejectedPatchAudit] = Field(default_factory=list)
    source_event_ids: list[str] = Field(default_factory=list)
    cited_memory_ids: list[str] = Field(default_factory=list)
    model_metadata: ModelMetadata = Field(default_factory=ModelMetadata)
    fallback_used: bool = False
    fallback_reasons: list[str] = Field(default_factory=list)
    validation_warnings: list[str] = Field(default_factory=list)
    prompt_layer_summaries: list[PromptLayerSummary] = Field(default_factory=list)
    replay_input: JsonMap = Field(default_factory=dict)
    log_summary: JsonMap = Field(default_factory=dict)

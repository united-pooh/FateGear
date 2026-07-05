"""场景运行时输入输出契约。"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, TypeAdapter

from ..story.models import StorySignal

if TYPE_CHECKING:
    pass


class KTSLBlockError(Exception):
    """Raised when KTSL blocks an intent at submit time OR during resolve."""

    def __init__(self, reason: str, *, reason_code: str = "") -> None:
        super().__init__(reason)
        self.reason = reason
        self.reason_code = reason_code


class MoveIntent(BaseModel):
    type: Literal["move"]
    target_scene_id: str = Field(..., min_length=1, max_length=30)


class ActionIntent(BaseModel):
    type: Literal["action"]
    action_id: str = Field(..., min_length=1, max_length=40)


class ObserveIntent(BaseModel):
    type: Literal["observe"]
    text: str = Field(..., min_length=1, max_length=300)


class FreeformIntent(BaseModel):
    type: Literal["freeform"]
    text: str = Field(..., min_length=1, max_length=300)
    freeform_kind: str = Field(default="", max_length=40)
    intended_target: str = Field(default="", max_length=80)
    risk_hint: str = Field(default="", max_length=800)
    requested_skill_key: str = Field(default="", max_length=50)


SceneIntent = MoveIntent | ActionIntent | ObserveIntent | FreeformIntent
SCENE_INTENT_ADAPTER: TypeAdapter[SceneIntent] = TypeAdapter(SceneIntent)


class IntentResolution(BaseModel):
    player_id: str
    scene_id: str
    intent_type: str
    success: bool
    reason: str = Field(default="")
    reason_code: str = Field(default="")
    violation_kind: str = Field(default="")
    penalty_tier: str = Field(default="")
    illegal_value: int | None = Field(default=None)
    target_scene_id: str = Field(default="")
    action_id: str = Field(default="")
    observation_text: str = Field(default="")
    freeform_text: str = Field(default="")
    freeform_kind: str = Field(default="")
    intended_target: str = Field(default="")
    risk_hint: str = Field(default="")
    requested_skill_key: str = Field(default="")
    effects_applied: list[str] = Field(default_factory=list)


class SceneBatchResolution(BaseModel):
    scene_id: str
    player_ids: list[str] = Field(default_factory=list)
    outcomes: list[IntentResolution] = Field(default_factory=list)
    # 运行时用 Any 避免循环导入；类型检查时为 KeeperNarration | None
    narration: Any = Field(
        default=None,
        description="Render 阶段 Agent 对本批次结果生成的叙事（KeeperNarration）；无 Agent 时为 None。",
    )


class RuntimeEvent(BaseModel):
    type: Literal[
        "turn_started",
        "no_pending_intents",
        "scene_batch_started",
        "movement_attempted",
        "observation_requested",
        "freeform_action_resolved",
        "movement_risk_updated",
        "movement_penalty_triggered",
        "action_resolved",
        "movement_committed",
        "flags_changed",
        "clocks_advanced",
        "clock_events_triggered",
        "story_transition_applied",
        "ending_reached",
        "turn_completed",
        "status_changed",
        "plan_agent_called",
        "plan_agent_skipped",
        "agent_effects_queued",
        "render_agent_called",
        "render_agent_skipped",
        "ktsl_intervention_issued",
        "ktsl_override_applied",
        "ktsl_audit_updated",
        "clue_fail_forward_delivered",
    ]
    message: str
    turn_no: int
    scene_id: str = Field(default="")
    scene_name: str = Field(default="")
    player_id: str = Field(default="")
    player_ids: list[str] = Field(default_factory=list)
    action_id: str = Field(default="")
    action_name: str = Field(default="")
    from_scene_id: str = Field(default="")
    from_scene_name: str = Field(default="")
    to_scene_id: str = Field(default="")
    to_scene_name: str = Field(default="")
    success: bool | None = Field(default=None)
    fallback_used: bool | None = Field(default=None)
    reason: str = Field(default="")
    reason_code: str = Field(default="")
    violation_kind: str = Field(default="")
    score_before: int | None = Field(default=None)
    score_after: int | None = Field(default=None)
    delta: int | None = Field(default=None)
    decay_applied: int = Field(default=0)
    threshold_crossed: str = Field(default="")
    penalty_tier: str = Field(default="")
    consecutive_count: int = Field(default=0)
    recent_window_count: int = Field(default=0)
    initialized: bool = Field(default=False)
    required_threshold: int | None = Field(default=None)
    actual_score: int | None = Field(default=None)
    source_event_id: str = Field(default="")
    effects_applied: list[str] = Field(default_factory=list)
    added_flags: list[str] = Field(default_factory=list)
    removed_flags: list[str] = Field(default_factory=list)
    clock_deltas: dict[str, int] = Field(default_factory=dict)
    triggered_clock_events: list[str] = Field(default_factory=list)
    ending_id: str = Field(default="")
    ending_result: str = Field(default="")
    clock_values: dict[str, int] = Field(default_factory=dict)
    story_transition_id: str = Field(default="")
    source_stage_id: str = Field(default="")
    target_stage_id: str = Field(default="")
    clue_id: str = Field(default="")
    info_id: str = Field(default="")
    route_ids: list[str] = Field(default_factory=list)

    def to_log_line(self) -> str:
        return self.message

    def __str__(self) -> str:
        return self.message


class DiceRollAudit(BaseModel):
    source: Literal[
        "static_action_check",
        "dynamic_agent_check",
        "runtime_freeform_check",
        "status_consequence",
    ]
    turn_no: int = Field(default=0)
    player_id: str = Field(default="")
    scene_id: str = Field(default="")
    scene_name: str = Field(default="")
    action_id: str = Field(default="")
    action_name: str = Field(default="")
    skill_key: str = Field(default="")
    difficulty: str = Field(default="")
    proposed_difficulty: str = Field(default="")
    roll_value: int = Field(default=0)
    threshold: int = Field(default=0)
    success: bool = Field(default=False)
    success_level: str = Field(default="")
    reason: str = Field(default="")
    note: str = Field(default="")
    visibility: Literal["public", "keeper"] = Field(default="public")
    roll_kind: str = Field(default="skill_check")
    label: str = Field(default="")
    notation: str = Field(default="")
    roll_values: list[int] = Field(default_factory=list)
    total: int = Field(default=0)
    status_target: str = Field(default="")
    status_before: int = Field(default=0)
    status_after: int = Field(default=0)
    status_delta: int = Field(default=0)
    penalty_dice: int = Field(default=0)
    display_text: str = Field(default="")


class AgentCallAudit(BaseModel):
    model_config = ConfigDict(protected_namespaces=())

    stage: Literal["plan", "render"]
    turn_no: int = Field(default=0)
    scene_id: str = Field(default="")
    scene_name: str = Field(default="")
    model_id: str = Field(default="")
    latency_ms: int = Field(default=0)
    attempt: int = Field(default=1)
    fallback_used: bool = Field(default=False)
    input_tokens: int = Field(default=0)
    output_tokens: int = Field(default=0)
    selected_context_ids: list[str] = Field(default_factory=list)
    output_summary: dict[str, object] = Field(default_factory=dict)


class TurnResolution(BaseModel):
    session_id: str
    turn_no: int
    next_turn: int
    scene_batches: list[SceneBatchResolution] = Field(default_factory=list)
    event_log: list[RuntimeEvent] = Field(default_factory=list)
    dice_rolls: list[DiceRollAudit] = Field(default_factory=list)
    agent_calls: list[AgentCallAudit] = Field(default_factory=list)
    applied_flags: list[str] = Field(default_factory=list)
    applied_clock_deltas: dict[str, int] = Field(default_factory=dict)
    triggered_clock_events: list[str] = Field(default_factory=list)
    clock_values: dict[str, int] = Field(default_factory=dict)
    story_signals: list[StorySignal] = Field(default_factory=list)
    current_stage_id: str = Field(default="")
    new_stage: str | None = Field(default=None)
    applied_story_transition_id: str | None = Field(default=None)
    resolved_ending: str | None = Field(default=None)
    ending_result: str = Field(default="")

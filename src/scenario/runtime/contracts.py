"""场景运行时输入输出契约。"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Literal

from pydantic import BaseModel, Field, TypeAdapter

from ..story.models import StorySignal

if TYPE_CHECKING:
    pass


class MoveIntent(BaseModel):
    type: Literal["move"]
    target_scene_id: str = Field(..., min_length=1, max_length=30)


class ActionIntent(BaseModel):
    type: Literal["action"]
    action_id: str = Field(..., min_length=1, max_length=40)


SceneIntent = MoveIntent | ActionIntent
SCENE_INTENT_ADAPTER: TypeAdapter[SceneIntent] = TypeAdapter(SceneIntent)


class IntentResolution(BaseModel):
    player_id: str
    scene_id: str
    intent_type: str
    success: bool
    reason: str = Field(default="")
    target_scene_id: str = Field(default="")
    action_id: str = Field(default="")
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
        "action_resolved",
        "movement_committed",
        "flags_changed",
        "clocks_advanced",
        "clock_events_triggered",
        "story_transition_applied",
        "ending_reached",
        "turn_completed",
        "plan_agent_called",
        "plan_agent_skipped",
        "render_agent_called",
        "render_agent_skipped",
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

    def to_log_line(self) -> str:
        return self.message

    def __str__(self) -> str:
        return self.message


class TurnResolution(BaseModel):
    session_id: str
    turn_no: int
    next_turn: int
    scene_batches: list[SceneBatchResolution] = Field(default_factory=list)
    event_log: list[RuntimeEvent] = Field(default_factory=list)
    applied_flags: list[str] = Field(default_factory=list)
    applied_clock_deltas: dict[str, int] = Field(default_factory=dict)
    triggered_clock_events: list[str] = Field(default_factory=list)
    clock_values: dict[str, int] = Field(default_factory=dict)
    story_signals: list[StorySignal] = Field(default_factory=list)
    new_stage: str | None = Field(default=None)
    applied_story_transition_id: str | None = Field(default=None)
    resolved_ending: str | None = Field(default=None)
    ending_result: str = Field(default="")

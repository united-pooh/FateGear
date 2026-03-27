"""剧情状态机模型与服务。"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator

from scene.module_types import ModuleEffect


class StoryState(BaseModel):
    current_stage_id: str = Field(..., min_length=1, max_length=40)
    stage_entered_turn: int = Field(default=1, ge=1)
    resolved_ending_id: str | None = Field(default=None, max_length=40)


class StoryStage(BaseModel):
    id: str = Field(..., min_length=1, max_length=40)
    name: str = Field(..., min_length=1, max_length=100)
    description: str = Field(default="", max_length=500)
    required_flags: list[str] = Field(default_factory=list, max_length=10)
    available_clues: list[str] = Field(default_factory=list, max_length=20)
    npc_presence_rules: list[str] = Field(default_factory=list, max_length=20)
    is_terminal: bool = Field(default=False)
    terminal_type: str = Field(default="", max_length=40)

    @model_validator(mode="after")
    def validate_terminal_fields(self) -> "StoryStage":
        if self.is_terminal and not self.terminal_type:
            raise ValueError("终局剧情阶段必须提供 terminal_type")
        if not self.is_terminal and self.terminal_type:
            raise ValueError("非终局剧情阶段不能设置 terminal_type")
        return self


class StorySignal(BaseModel):
    type: Literal[
        "scene_entered",
        "action_succeeded",
        "clock_threshold_triggered",
    ]
    turn_no: int = Field(..., ge=1)
    player_id: str = Field(default="", max_length=30)
    scene_id: str = Field(default="", max_length=30)
    action_id: str = Field(default="", max_length=40)
    clock_id: str = Field(default="", max_length=40)
    threshold: int = Field(default=0, ge=0)


class StoryTransition(BaseModel):
    id: str = Field(..., min_length=1, max_length=40)
    source_stage_id: str = Field(..., min_length=1, max_length=40)
    target_stage_id: str = Field(..., min_length=1, max_length=40)
    required_flags: list[str] = Field(default_factory=list, max_length=10)
    trigger_type: Literal[
        "scene_entered",
        "action_succeeded",
        "clock_threshold_triggered",
    ]
    trigger_value: str = Field(..., min_length=1, max_length=80)
    priority: int = Field(default=100, ge=0)
    effects: list[ModuleEffect] = Field(default_factory=list)


class TransitionValidator:
    """剧情迁移校验器。"""

    def can_transition(
        self,
        *,
        story_state: StoryState,
        stages: dict[str, StoryStage],
        transitions: list[StoryTransition],
        signals: list[StorySignal],
        flags: set[str],
    ) -> StoryTransition | None:
        candidate_transitions = sorted(
            (
                transition
                for transition in transitions
                if transition.source_stage_id == story_state.current_stage_id
            ),
            key=lambda item: item.priority,
        )

        for transition in candidate_transitions:
            if not self._required_flags_met(
                transition.required_flags,
                flags=flags,
            ):
                continue
            if not any(
                self._signal_matches_transition(signal, transition)
                for signal in signals
            ):
                continue
            if not self._target_stage_unlocked(
                stages[transition.target_stage_id],
                flags=flags,
                transition=transition,
            ):
                continue
            return transition
        return None

    def _signal_matches_transition(
        self,
        signal: StorySignal,
        transition: StoryTransition,
    ) -> bool:
        if signal.type != transition.trigger_type:
            return False
        if transition.trigger_type == "scene_entered":
            return signal.scene_id == transition.trigger_value
        if transition.trigger_type == "action_succeeded":
            return signal.action_id == transition.trigger_value
        if transition.trigger_type == "clock_threshold_triggered":
            return f"{signal.clock_id}:{signal.threshold}" == transition.trigger_value
        return False

    def _required_flags_met(
        self,
        required_flags: list[str],
        *,
        flags: set[str],
    ) -> bool:
        return all(flag in flags for flag in required_flags)

    def _target_stage_unlocked(
        self,
        stage: StoryStage,
        *,
        flags: set[str],
        transition: StoryTransition,
    ) -> bool:
        projected_flags = set(flags)
        for effect in transition.effects:
            if effect.type == "set_flag":
                projected_flags.add(effect.flag)
            elif effect.type == "clear_flag":
                projected_flags.discard(effect.flag)
        return self._required_flags_met(stage.required_flags, flags=projected_flags)


class StoryStateService:
    """剧情状态写入服务。"""

    def apply_transition(
        self,
        *,
        story_state: StoryState,
        transition: StoryTransition,
        stages: dict[str, StoryStage],
        turn_no: int,
    ) -> StoryState:
        target_stage = stages[transition.target_stage_id]
        return StoryState(
            current_stage_id=transition.target_stage_id,
            stage_entered_turn=turn_no,
            resolved_ending_id=(
                transition.target_stage_id if target_stage.is_terminal else None
            ),
        )

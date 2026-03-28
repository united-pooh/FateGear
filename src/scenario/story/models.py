"""剧情状态机模型。"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator

from ..module.types import ModuleEffect


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

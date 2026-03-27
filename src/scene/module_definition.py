"""YAML 模组静态定义模型。"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator


class ModuleScene(BaseModel):
    id: str = Field(..., min_length=1, max_length=30)
    name: str = Field(..., min_length=1, max_length=100)
    description: str = Field(default="", max_length=1000)
    tags: list[str] = Field(default_factory=list, max_length=10)


class ModuleLink(BaseModel):
    id: str = Field(..., min_length=1, max_length=40)
    from_scene_id: str = Field(..., min_length=1, max_length=30)
    to_scene_id: str = Field(..., min_length=1, max_length=30)
    required_flags: list[str] = Field(default_factory=list, max_length=10)
    block_reason: str = Field(default="", max_length=200)


class ModuleCondition(BaseModel):
    type: Literal["flag_set", "flag_unset", "action_completed", "clock_at_least"]
    flag: str = Field(default="", max_length=40)
    action_id: str = Field(default="", max_length=40)
    clock_id: str = Field(default="", max_length=40)
    value: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def validate_fields(self) -> "ModuleCondition":
        if self.type in {"flag_set", "flag_unset"} and not self.flag:
            raise ValueError("flag 条件需要提供 flag 字段")
        if self.type == "action_completed" and not self.action_id:
            raise ValueError("action_completed 条件需要提供 action_id 字段")
        if self.type == "clock_at_least" and not self.clock_id:
            raise ValueError("clock_at_least 条件需要提供 clock_id 字段")
        return self


class ModuleEffect(BaseModel):
    type: Literal["set_flag", "clear_flag", "advance_clock"]
    flag: str = Field(default="", max_length=40)
    clock_id: str = Field(default="", max_length=40)
    value: int = Field(default=0, ge=0)

    @model_validator(mode="after")
    def validate_fields(self) -> "ModuleEffect":
        if self.type in {"set_flag", "clear_flag"} and not self.flag:
            raise ValueError("flag 效果需要提供 flag 字段")
        if self.type == "advance_clock":
            if not self.clock_id:
                raise ValueError("advance_clock 效果需要提供 clock_id 字段")
            if self.value <= 0:
                raise ValueError("advance_clock 效果需要提供大于 0 的 value")
        return self


class ClockThresholdEvent(BaseModel):
    value: int = Field(..., ge=0)
    effects: list[ModuleEffect] = Field(default_factory=list)


class ModuleClock(BaseModel):
    id: str = Field(..., min_length=1, max_length=40)
    start: int = Field(default=0, ge=0)
    max_value: int = Field(default=10, ge=0)
    step_per_turn: int = Field(default=1, ge=0)
    threshold_events: list[ClockThresholdEvent] = Field(default_factory=list)


class ModuleAction(BaseModel):
    id: str = Field(..., min_length=1, max_length=40)
    scene_id: str = Field(..., min_length=1, max_length=30)
    name: str = Field(..., min_length=1, max_length=100)
    kind: str = Field(..., min_length=1, max_length=30)
    once: bool = Field(default=True)
    conditions: list[ModuleCondition] = Field(default_factory=list)
    effects_on_success: list[ModuleEffect] = Field(default_factory=list)
    effects_on_failure: list[ModuleEffect] = Field(default_factory=list)
    marks_scene_cleared: bool = Field(default=False)


class ModuleEnding(BaseModel):
    id: str = Field(..., min_length=1, max_length=40)
    scene_id: str = Field(..., min_length=1, max_length=30)
    conditions: list[ModuleCondition] = Field(default_factory=list)
    result: str = Field(..., min_length=1, max_length=200)


class ModuleDefinition(BaseModel):
    module_id: str = Field(..., min_length=1, max_length=30)
    title: str = Field(..., min_length=1, max_length=100)
    version: int = Field(default=1, ge=1)
    entry_scene_id: str = Field(..., min_length=1, max_length=30)
    flags: list[str] = Field(default_factory=list)
    scenes: list[ModuleScene] = Field(default_factory=list)
    links: list[ModuleLink] = Field(default_factory=list)
    actions: list[ModuleAction] = Field(default_factory=list)
    clocks: list[ModuleClock] = Field(default_factory=list)
    endings: list[ModuleEnding] = Field(default_factory=list)

    def scene_map(self) -> dict[str, ModuleScene]:
        return {scene.id: scene for scene in self.scenes}

    def link_map(self) -> dict[str, ModuleLink]:
        return {link.id: link for link in self.links}

    def action_map(self) -> dict[str, ModuleAction]:
        return {action.id: action for action in self.actions}

    def clock_map(self) -> dict[str, ModuleClock]:
        return {clock.id: clock for clock in self.clocks}

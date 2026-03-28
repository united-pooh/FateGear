"""YAML 模组共享的条件与效果模型。"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, model_validator


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

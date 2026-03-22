from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, ValidationInfo, field_validator

from cards.domain.enums import MentalState, PhysicalState
from cards.rules.derived import DerivedStats

HitPoints = Annotated[int, Field(ge=0, le=19, strict=True)]
MagicPoints = Annotated[int, Field(ge=0, le=19, strict=True)]
SanityPoints = Annotated[int, Field(ge=0, le=99, strict=True)]
HitPointsMax = Annotated[int, Field(ge=0, le=19, strict=True)]
MagicPointsMax = Annotated[int, Field(ge=0, le=19, strict=True)]
SanityMax = Annotated[int, Field(ge=0, le=99, strict=True)]
SpecialStateText = Annotated[str, Field(min_length=1, max_length=30)]


class InvestigatorState(BaseModel):
    model_config = ConfigDict(validate_assignment=True)

    # 理论边界来自 7版规则与当前属性范围（1..99）
    hit_points_max: HitPointsMax = Field(frozen=True, exclude=True)
    magic_points_max: MagicPointsMax = Field(frozen=True, exclude=True)
    sanity_max: SanityMax = Field(frozen=True, exclude=True)
    hit_points: HitPoints
    magic_points: MagicPoints
    sanity: SanityPoints
    physical_state: PhysicalState = Field(default=PhysicalState.HEALTHY)
    mental_state: MentalState = Field(default=MentalState.CLEAR)
    special_state: SpecialStateText = Field(default="无特殊状态")

    @field_validator("hit_points", mode="before")
    @classmethod
    def _clamp_hit_points(cls, value: object, info: ValidationInfo) -> object:
        max_value = info.data.get("hit_points_max")
        if (
            max_value is None
            or not isinstance(value, int)
            or isinstance(value, bool)
        ):
            return value
        return min(max(value, 0), max_value)

    @field_validator("magic_points", mode="before")
    @classmethod
    def _clamp_magic_points(cls, value: object, info: ValidationInfo) -> object:
        max_value = info.data.get("magic_points_max")
        if (
            max_value is None
            or not isinstance(value, int)
            or isinstance(value, bool)
        ):
            return value
        return min(max(value, 0), max_value)

    @field_validator("sanity", mode="before")
    @classmethod
    def _clamp_sanity(cls, value: object, info: ValidationInfo) -> object:
        max_value = info.data.get("sanity_max")
        if (
            max_value is None
            or not isinstance(value, int)
            or isinstance(value, bool)
        ):
            return value
        return min(max(value, 0), max_value)

    @classmethod
    def from_derived_stats(cls, derived: DerivedStats) -> "InvestigatorState":
        return cls.model_validate(
            {
                "hit_points_max": derived.hit_points_max,
                "magic_points_max": derived.magic_points_max,
                "sanity_max": derived.sanity_max,
                "hit_points": derived.hit_points_max,
                "magic_points": derived.magic_points_max,
                "sanity": derived.starting_sanity,
            }
        )

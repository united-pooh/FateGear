from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, model_validator

FlatBonus = Annotated[int, Field(strict=True)]
DiceCount = Annotated[int, Field(ge=0, strict=True)]
DieSides = Annotated[int, Field(ge=0, strict=True)]


class DamageBonus(BaseModel):
    """结构化的伤害加值，便于后续战斗代码直接消费。"""

    model_config = ConfigDict(frozen=True)

    flat: FlatBonus = 0
    dice_count: DiceCount = 0
    die_sides: DieSides = 0

    @model_validator(mode="after")
    def _validate_dice_shape(self) -> "DamageBonus":
        if self.dice_count < 0:
            raise ValueError("dice_count must be zero or positive")
        if self.die_sides < 0:
            raise ValueError("die_sides must be zero or positive")
        if self.dice_count == 0 and self.die_sides != 0:
            raise ValueError("die_sides must be zero when dice_count is zero")
        if self.dice_count > 0 and self.die_sides == 0:
            raise ValueError("die_sides must be positive when dice_count is positive")
        if self.flat and self.dice_count:
            raise ValueError("flat and dice bonuses are modeled separately")
        return self

    @property
    def notation(self) -> str:
        if self.dice_count:
            return f"+{self.dice_count}D{self.die_sides}"
        if self.flat > 0:
            return f"+{self.flat}"
        return str(self.flat)

    def __str__(self) -> str:
        return self.notation

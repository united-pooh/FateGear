from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

PercentileStat = Annotated[int, Field(ge=1, le=99, strict=True)]
LuckStat = Annotated[int, Field(ge=0, le=99, strict=True)]


class InvestigatorAttributes(BaseModel):
    """第七版克苏鲁调查员的属性块。"""

    strength: PercentileStat
    constitution: PercentileStat
    size: PercentileStat
    dexterity: PercentileStat
    appearance: PercentileStat
    intelligence: PercentileStat
    power: PercentileStat
    education: PercentileStat
    luck: LuckStat | None = None

    model_config = ConfigDict(frozen=True)

    @property
    def strength_plus_size(self) -> int:
        return self.strength + self.size

    def as_dict(self) -> dict[str, int | None]:
        mapping = {
            "strength": "STR",
            "constitution": "CON",
            "size": "SIZ",
            "dexterity": "DEX",
            "appearance": "APP",
            "intelligence": "INT",
            "power": "POW",
            "education": "EDU",
            "luck": "Luck",
        }
        data = self.model_dump()
        return {mapping[k]: v for k, v in data.items()}

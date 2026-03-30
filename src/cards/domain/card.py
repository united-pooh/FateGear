from __future__ import annotations

from typing import Annotated
from collections.abc import Mapping

from pydantic import BaseModel, Field

from cards.domain.attributes import InvestigatorAttributes
from cards.domain.skills import InvestigatorSkill, SkillKey
from cards.domain.state import InvestigatorState
from cards.rules.derived import DerivedStats, derive_stats

Name = Annotated[str, Field(min_length=3, max_length=30)]
Age = Annotated[int, Field(ge=1, le=120, strict=True)]
Occupation = Annotated[str, Field(min_length=0, max_length=30)]
Player = Annotated[str, Field(min_length=0, max_length=30)]
CthulhuMythos = Annotated[int, Field(ge=0, le=99, strict=True)]


class InvestigatorCard(BaseModel):
    name: Name
    age: Age
    attributes: InvestigatorAttributes
    derived: DerivedStats
    state: InvestigatorState
    occupation: Occupation
    player: Player
    cthulhu_mythos: CthulhuMythos
    skills: dict[SkillKey, InvestigatorSkill] = Field(default_factory=dict)

    @classmethod
    def create(
        cls,
        *,
        name: Name,
        age: Age,
        attributes: InvestigatorAttributes,
        occupation: Occupation = "",
        player: Player = "",
        cthulhu_mythos: CthulhuMythos = 0,
        skills: Mapping[SkillKey, InvestigatorSkill] | None = None,
    ) -> InvestigatorCard:
        derived = derive_stats(
            attributes=attributes,
            age=age,
            cthulhu_mythos=cthulhu_mythos,
        )
        state = InvestigatorState.from_derived_stats(derived)
        return cls(
            name=name,
            age=age,
            attributes=attributes,
            derived=derived,
            state=state,
            occupation=occupation,
            player=player,
            cthulhu_mythos=cthulhu_mythos,
            skills=dict(skills) if skills is not None else {},
        )

    def modify_hit_point(self, amount: int) -> None:
        self.state.hit_points += amount

    def modify_magic_point(self, amount: int) -> None:
        self.state.magic_points += amount

    def modify_sanity(self, amount: int) -> None:
        """修改当前 SAN，边界由 InvestigatorState 的 Pydantic 校验负责。"""
        self.state.sanity += amount

from __future__ import annotations

from dataclasses import dataclass

from cards.domain.attributes import InvestigatorAttributes
from cards.domain.state import InvestigatorState
from cards.rules.derived import DerivedStats, derive_stats


@dataclass(slots=True)
class InvestigatorCard:
    name: str
    age: int
    attributes: InvestigatorAttributes
    derived: DerivedStats
    state: InvestigatorState
    occupation: str = ""
    player: str = ""
    cthulhu_mythos: int = 0

    @classmethod
    def create(
        cls,
        *,
        name: str,
        age: int,
        attributes: InvestigatorAttributes,
        occupation: str = "",
        player: str = "",
        cthulhu_mythos: int = 0,
    ) -> "InvestigatorCard":
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
        )

    def modify_hit_point(self, amount: int) -> None:
        self.state.hit_points += amount
        # 边界约束
        if self.state.hit_points > self.derived.hit_points_max:
            self.state.hit_points = self.derived.hit_points_max
        if self.state.hit_points < 0:
            self.state.hit_points = 0
            # TODO: hp <= 0 进入 濒死/死亡 状态变更

        # TODO: amount 数值过大进入额外的判断


    def modify_magic_point(self, amount: int):
        self.state.magic_points += amount
        if self.state.magic_points > self.derived.magic_points_max:
            self.state.magic_points = self.derived.magic_points_max
        if self.state.magic_points < 0:
            self.state.magic_points = 0

    def modify_sanity(self, amount: int) -> None:
        """修改当前SAN, 且不能超过 SAN Max"""
        self.state.sanity += amount
        if self.state.sanity > self.derived.sanity_max:
            self.state.sanity = self.derived.sanity_max
        if self.state.sanity < 0:
            self.state.sanity = 0
            # TODO: san <= 0 状态变更

        # TODO: amount 数值过大进入额外的判断


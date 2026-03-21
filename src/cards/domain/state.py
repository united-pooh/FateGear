from __future__ import annotations

from dataclasses import dataclass

from cards.domain.enums import MentalState, PhysicalState
from cards.rules.derived import DerivedStats


@dataclass(slots=True)
class InvestigatorState:
    hit_points: int
    magic_points: int
    sanity: int
    physical_state: PhysicalState = PhysicalState.HEALTHY
    mental_state: MentalState = MentalState.CLEAR
    special_state: str = "无特殊状态"

    @classmethod
    def from_derived_stats(cls, derived: DerivedStats) -> "InvestigatorState":
        return cls(
            hit_points=derived.hit_points_max,
            magic_points=derived.magic_points_max,
            sanity=derived.starting_sanity,
        )

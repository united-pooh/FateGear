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

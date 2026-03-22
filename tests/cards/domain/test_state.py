from __future__ import annotations

import pytest
from pydantic import ValidationError

from cards.domain.attributes import InvestigatorAttributes
from cards.domain.state import InvestigatorState
from cards.rules.derived import derive_stats


def _make_state() -> InvestigatorState:
    attributes = InvestigatorAttributes(
        strength=60,
        constitution=60,
        size=60,
        dexterity=60,
        appearance=50,
        intelligence=60,
        power=80,
        education=70,
        luck=50,
    )
    # mythos=60 -> sanity_max=39，用来验证动态上限裁剪。
    derived = derive_stats(attributes=attributes, age=25, cthulhu_mythos=60)
    return InvestigatorState.from_derived_stats(derived)


def test_state_clamps_values_via_pydantic_assignment_validation() -> None:
    state = _make_state()

    state.hit_points = 999
    assert state.hit_points == state.hit_points_max

    state.magic_points = -100
    assert state.magic_points == 0

    state.sanity = 80
    assert state.sanity == state.sanity_max


def test_state_max_fields_are_frozen() -> None:
    state = _make_state()

    with pytest.raises(ValidationError):
        state.hit_points_max = 1

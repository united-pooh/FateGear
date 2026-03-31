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


def test_state_accepts_hp_mp_boundary_19_from_derived_stats() -> None:
    attributes = InvestigatorAttributes(
        strength=99,
        constitution=99,
        size=99,
        dexterity=99,
        appearance=99,
        intelligence=99,
        power=99,
        education=99,
        luck=99,
    )
    derived = derive_stats(attributes=attributes, age=25)

    state = InvestigatorState.from_derived_stats(derived)

    assert state.hit_points_max == 19
    assert state.magic_points_max == 19
    assert state.hit_points == 19
    assert state.magic_points == 19


def test_state_rejects_manual_max_value_above_boundary() -> None:
    with pytest.raises(ValidationError):
        InvestigatorState(
            hit_points_max=20,
            magic_points_max=19,
            sanity_max=99,
            hit_points=19,
            magic_points=19,
            sanity=50,
        )

import pytest

from cards.domain.attributes import InvestigatorAttributes
from cards.rules.derived import (
    calculate_build,
    calculate_damage_bonus,
    calculate_move_rate,
    derive_stats,
    calculate_hit_points,
    calculate_magic_points
)


def _make_attributes(
    *, strength: int, dexterity: int, size: int, power: int = 50
) -> InvestigatorAttributes:
    return InvestigatorAttributes(
        strength=strength,
        constitution=50,
        size=size,
        dexterity=dexterity,
        appearance=50,
        intelligence=50,
        power=power,
        education=80,
        luck=50,
    )


@pytest.mark.parametrize(
    ("strength", "size", "expected_build", "expected_bonus"),
    [
        (30, 30, -2, "-2"),
        (40, 30, -1, "-1"),
        (45, 45, 0, "0"),
        (80, 60, 1, "+1D4"),
        (95, 85, 2, "+1D6"),
    ],
)
def test_damage_bonus_and_build_thresholds(
    strength: int, size: int, expected_build: int, expected_bonus: str
) -> None:
    attributes = _make_attributes(strength=strength, dexterity=70, size=size)

    assert calculate_build(attributes) == expected_build
    assert calculate_damage_bonus(attributes).notation == expected_bonus


def test_move_rate_respects_body_comparison_and_age_penalty() -> None:
    fast = _make_attributes(strength=80, dexterity=80, size=60)
    average = _make_attributes(strength=80, dexterity=60, size=60)
    slow = _make_attributes(strength=40, dexterity=40, size=60)

    assert calculate_move_rate(fast, age=20) == 9
    assert calculate_move_rate(average, age=20) == 8
    assert calculate_move_rate(slow, age=20) == 7
    assert calculate_move_rate(fast, age=55) == 7


def test_sanity_is_capped_by_cthulhu_mythos() -> None:
    attributes = _make_attributes(strength=70, dexterity=60, size=60, power=80)

    derived = derive_stats(attributes, age=28, cthulhu_mythos=60)

    assert derived.starting_sanity == 39
    assert derived.sanity_max == 39



def test_hit_points_calculation() -> None:
    attributes = _make_attributes(strength=50, dexterity=50, size=60)
    attributes = attributes.__class__(**{**attributes.as_dict(), "CON": 50, "SIZ":65})
    assert calculate_hit_points(attributes) == 11

def test_magic_points_calculation() -> None:
    attributes = _make_attributes(strength=50, dexterity=50, size=60)
    assert calculate_magic_points(attributes) == 13
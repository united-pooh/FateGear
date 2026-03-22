import pytest
from pydantic import ValidationError

from cards.domain.value_objects import DamageBonus


def test_damage_bonus_notation() -> None:
    assert DamageBonus(flat=-2).notation == "-2"
    assert DamageBonus(flat=2).notation == "+2"
    assert DamageBonus(dice_count=1, die_sides=4).notation == "+1D4"


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"dice_count": 0, "die_sides": 4}, "die_sides must be zero when dice_count is zero"),
        ({"dice_count": 1, "die_sides": 0}, "die_sides must be positive when dice_count is positive"),
        ({"flat": 1, "dice_count": 1, "die_sides": 4}, "flat and dice bonuses are modeled separately"),
    ],
)
def test_damage_bonus_rejects_invalid_shapes(
    kwargs: dict[str, int],
    message: str,
) -> None:
    with pytest.raises(ValidationError, match=message):
        DamageBonus(**kwargs)

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
        ({"dice_count": 0, "die_sides": 4}, "当 dice_count 为 0 时，die_sides 也必须为 0"),
        ({"dice_count": 1, "die_sides": 0}, "当 dice_count 大于 0 时，die_sides 必须大于 0"),
        ({"flat": 1, "dice_count": 1, "die_sides": 4}, "flat 加值和骰子加值必须分开表示"),
    ],
)
def test_damage_bonus_rejects_invalid_shapes(
    kwargs: dict[str, int],
    message: str,
) -> None:
    with pytest.raises(ValidationError, match=message):
        DamageBonus(**kwargs)

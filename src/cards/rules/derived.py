from __future__ import annotations

from dataclasses import dataclass

from cards.domain.attributes import InvestigatorAttributes
from cards.domain.value_objects import DamageBonus


@dataclass(frozen=True, slots=True)
class DerivedStats:
    hit_points_max: int
    magic_points_max: int
    starting_sanity: int
    sanity_max: int
    move_rate: int
    build: int
    damage_bonus: DamageBonus


def _validate_age(age: int) -> None:
    if isinstance(age, bool) or not isinstance(age, int):
        raise TypeError("age must be an int")
    if not 1 <= age <= 120:
        raise ValueError(f"age must be between 1 and 120, got {age}")


def _validate_mythos(cthulhu_mythos: int) -> None:
    if isinstance(cthulhu_mythos, bool) or not isinstance(cthulhu_mythos, int):
        raise TypeError("cthulhu_mythos must be an int")
    if not 0 <= cthulhu_mythos <= 99:
        raise ValueError(
            f"cthulhu_mythos must be between 0 and 99, got {cthulhu_mythos}"
        )


def calculate_hit_points(attributes: InvestigatorAttributes) -> int:
    return (attributes.constitution + attributes.size) // 10


def calculate_magic_points(attributes: InvestigatorAttributes) -> int:
    return attributes.power // 5


def calculate_sanity_max(cthulhu_mythos: int = 0) -> int:
    _validate_mythos(cthulhu_mythos)
    return max(0, 99 - cthulhu_mythos)


def calculate_starting_sanity(
    attributes: InvestigatorAttributes, cthulhu_mythos: int = 0
) -> int:
    return min(attributes.power, calculate_sanity_max(cthulhu_mythos))


def calculate_age_penalty(age: int) -> int:
    _validate_age(age)
    if age < 40:
        return 0
    return min(5, (age // 10) - 3)


def calculate_base_move_rate(attributes: InvestigatorAttributes) -> int:
    if attributes.strength < attributes.size and attributes.dexterity < attributes.size:
        return 7
    if attributes.strength > attributes.size and attributes.dexterity > attributes.size:
        return 9
    return 8


def calculate_move_rate(attributes: InvestigatorAttributes, age: int) -> int:
    move_rate = calculate_base_move_rate(attributes) - calculate_age_penalty(age)
    return max(1, move_rate)


def calculate_damage_bonus(attributes: InvestigatorAttributes) -> DamageBonus:
    total = attributes.strength_plus_size
    if total < 65:
        return DamageBonus(flat=-2)
    if total < 85:
        return DamageBonus(flat=-1)
    if total < 125:
        return DamageBonus(flat=0)
    if total < 165:
        return DamageBonus(dice_count=1, die_sides=4)
    return DamageBonus(dice_count=1, die_sides=6)


def calculate_build(attributes: InvestigatorAttributes) -> int:
    total = attributes.strength_plus_size
    if total < 65:
        return -2
    if total < 85:
        return -1
    if total < 125:
        return 0
    if total < 165:
        return 1
    return 2


def derive_stats(
    attributes: InvestigatorAttributes, age: int, cthulhu_mythos: int = 0
) -> DerivedStats:
    return DerivedStats(
        hit_points_max=calculate_hit_points(attributes),
        magic_points_max=calculate_magic_points(attributes),
        starting_sanity=calculate_starting_sanity(attributes, cthulhu_mythos),
        sanity_max=calculate_sanity_max(cthulhu_mythos),
        move_rate=calculate_move_rate(attributes, age),
        build=calculate_build(attributes),
        damage_bonus=calculate_damage_bonus(attributes),
    )

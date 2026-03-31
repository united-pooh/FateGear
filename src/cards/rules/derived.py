from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, validate_call

from cards.domain.attributes import InvestigatorAttributes
from cards.domain.value_objects import DamageBonus

Age = Annotated[int, Field(ge=1, le=120, strict=True)]
CthulhuMythos = Annotated[int, Field(ge=0, le=99, strict=True)]
HitPointsMax = Annotated[int, Field(ge=0, le=19, strict=True)]
MagicPointsMax = Annotated[int, Field(ge=0, le=19, strict=True)]
SanityScore = Annotated[int, Field(ge=0, le=99, strict=True)]
MoveRate = Annotated[int, Field(ge=1, le=9, strict=True)]
BuildScore = Annotated[int, Field(ge=-2, le=2, strict=True)]


class DerivedStats(BaseModel):
    """调查员的衍生值快照。

    这些值由构卡时的输入计算得到，作为规则基线，不随局内消耗实时变化。
    """

    model_config = ConfigDict(frozen=True)

    hit_points_max: HitPointsMax
    magic_points_max: MagicPointsMax
    starting_sanity: SanityScore
    sanity_max: SanityScore
    move_rate: MoveRate
    build: BuildScore
    damage_bonus: DamageBonus


def calculate_hit_points(attributes: InvestigatorAttributes) -> int:
    """按 COC7 规则计算 HP 上限: (CON + SIZ) // 10。"""
    return (attributes.constitution + attributes.size) // 10


def calculate_magic_points(attributes: InvestigatorAttributes) -> int:
    """按 COC7 规则计算 MP 上限: POW // 5。"""
    return attributes.power // 5


@validate_call
def calculate_sanity_max(cthulhu_mythos: CthulhuMythos = 0) -> int:
    return max(0, 99 - cthulhu_mythos)


def calculate_starting_sanity(
    attributes: InvestigatorAttributes, cthulhu_mythos: int = 0
) -> int:
    """初始 SAN 不超过 POW，也不超过 SAN 上限。"""
    return min(attributes.power, calculate_sanity_max(cthulhu_mythos))


@validate_call
def calculate_age_penalty(age: Age) -> int:
    if age < 40:
        return 0
    return min(5, (age // 10) - 3)


def calculate_base_move_rate(attributes: InvestigatorAttributes) -> int:
    """不含年龄惩罚时的 MOV。"""
    if attributes.strength < attributes.size and attributes.dexterity < attributes.size:
        return 7
    if attributes.strength > attributes.size and attributes.dexterity > attributes.size:
        return 9
    return 8


def calculate_move_rate(attributes: InvestigatorAttributes, age: int) -> int:
    """应用年龄惩罚后的 MOV，且保证最小为 1。"""
    move_rate = calculate_base_move_rate(attributes) - calculate_age_penalty(age)
    return max(1, move_rate)


def calculate_damage_bonus(attributes: InvestigatorAttributes) -> DamageBonus:
    """按 STR+SIZ 区间计算伤害加值。"""
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
    """按 STR+SIZ 区间计算体格。"""
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
    """统一计算调查员卡的全部衍生值。"""
    return DerivedStats(
        hit_points_max=calculate_hit_points(attributes),
        magic_points_max=calculate_magic_points(attributes),
        starting_sanity=calculate_starting_sanity(attributes, cthulhu_mythos),
        sanity_max=calculate_sanity_max(cthulhu_mythos),
        move_rate=calculate_move_rate(attributes, age),
        build=calculate_build(attributes),
        damage_bonus=calculate_damage_bonus(attributes),
    )

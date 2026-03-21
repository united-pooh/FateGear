from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from cards.domain.attributes import InvestigatorAttributes
from cards.domain.card import InvestigatorCard

FIELD_ALIASES: dict[str, tuple[str, ...]] = {
    "name": ("name", "姓名"),
    "player": ("player", "玩家"),
    "occupation": ("occupation", "职业"),
    "age": ("age", "年龄"),
    "strength": ("strength", "str_", "str", "STR", "力量"),
    "constitution": ("constitution", "con", "CON", "体质"),
    "size": ("size", "siz", "SIZ", "体型"),
    "dexterity": ("dexterity", "dex", "DEX", "敏捷"),
    "appearance": ("appearance", "app", "APP", "外貌"),
    "intelligence": ("intelligence", "int_", "int", "INT", "智力"),
    "power": ("power", "pow", "POW", "意志"),
    "education": ("education", "edu", "EDU", "教育"),
    "luck": ("luck", "Luck", "幸运"),
    "cthulhu_mythos": ("cthulhu_mythos", "克苏鲁神话", "Cthulhu Mythos"),
}


def _pick(payload: Mapping[str, Any], *aliases: str) -> Any | None:
    for alias in aliases:
        if alias in payload and payload[alias] not in (None, ""):
            return payload[alias]
    return None


def _coerce_int(field_name: str, value: Any) -> int:
    if isinstance(value, bool):
        raise TypeError(f"{field_name} must be an int-compatible value")
    if isinstance(value, int):
        return value
    if isinstance(value, float) and value.is_integer():
        return int(value)
    if isinstance(value, str):
        text = value.strip()
        if not text:
            raise ValueError(f"{field_name} cannot be empty")
        try:
            return int(text)
        except ValueError:
            numeric = float(text)
            if numeric.is_integer():
                return int(numeric)
    raise TypeError(f"{field_name} must be an int-compatible value")


def _require_int(payload: Mapping[str, Any], field_name: str) -> int:
    value = _pick(payload, *FIELD_ALIASES[field_name])
    if value is None:
        aliases = ", ".join(FIELD_ALIASES[field_name])
        raise KeyError(f"missing required field {field_name}; expected one of: {aliases}")
    return _coerce_int(field_name, value)


def _optional_int(payload: Mapping[str, Any], field_name: str) -> int | None:
    value = _pick(payload, *FIELD_ALIASES[field_name])
    if value is None:
        return None
    return _coerce_int(field_name, value)


def build_investigator_card(
    *,
    name: str,
    age: int,
    strength: int,
    constitution: int,
    size: int,
    dexterity: int,
    appearance: int,
    intelligence: int,
    power: int,
    education: int,
    occupation: str = "",
    player: str = "",
    luck: int | None = None,
    cthulhu_mythos: int = 0,
) -> InvestigatorCard:
    attributes = InvestigatorAttributes(
        strength=strength,
        constitution=constitution,
        size=size,
        dexterity=dexterity,
        appearance=appearance,
        intelligence=intelligence,
        power=power,
        education=education,
        luck=luck,
    )
    return InvestigatorCard.create(
        name=name,
        age=age,
        attributes=attributes,
        occupation=occupation,
        player=player,
        cthulhu_mythos=cthulhu_mythos,
    )


def build_investigator_from_mapping(payload: Mapping[str, Any]) -> InvestigatorCard:
    name = _pick(payload, *FIELD_ALIASES["name"]) or "未命名调查员"
    player = _pick(payload, *FIELD_ALIASES["player"]) or ""
    occupation = _pick(payload, *FIELD_ALIASES["occupation"]) or ""
    return build_investigator_card(
        name=str(name),
        player=str(player),
        occupation=str(occupation),
        age=_require_int(payload, "age"),
        strength=_require_int(payload, "strength"),
        constitution=_require_int(payload, "constitution"),
        size=_require_int(payload, "size"),
        dexterity=_require_int(payload, "dexterity"),
        appearance=_require_int(payload, "appearance"),
        intelligence=_require_int(payload, "intelligence"),
        power=_require_int(payload, "power"),
        education=_require_int(payload, "education"),
        luck=_optional_int(payload, "luck"),
        cthulhu_mythos=_optional_int(payload, "cthulhu_mythos") or 0,
    )

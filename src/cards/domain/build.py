from __future__ import annotations

from collections.abc import Mapping
from typing import Annotated, Any

from pydantic import (
    AliasChoices,
    BaseModel,
    ConfigDict,
    Field,
    validate_call,
    model_validator,
)

from cards.domain.attributes import InvestigatorAttributes, LuckStat, PercentileStat
from cards.domain.card import (
    CthulhuMythos,
    InvestigatorCard,
    Name,
    Occupation,
    Player,
)

Age = Annotated[int, Field(ge=1, le=120, strict=True)]

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


def _alias_choices(field_name: str) -> AliasChoices:
    return AliasChoices(*FIELD_ALIASES[field_name])


class InvestigatorBuildPayload(BaseModel):
    model_config = ConfigDict(extra="ignore")

    name: Name = Field(default="未命名调查员", validation_alias=_alias_choices("name"))
    player: Player = Field(default="", validation_alias=_alias_choices("player"))
    occupation: Occupation = Field(
        default="", validation_alias=_alias_choices("occupation")
    )
    age: Age = Field(validation_alias=_alias_choices("age"))
    strength: PercentileStat = Field(validation_alias=_alias_choices("strength"))
    constitution: PercentileStat = Field(
        validation_alias=_alias_choices("constitution")
    )
    size: PercentileStat = Field(validation_alias=_alias_choices("size"))
    dexterity: PercentileStat = Field(validation_alias=_alias_choices("dexterity"))
    appearance: PercentileStat = Field(validation_alias=_alias_choices("appearance"))
    intelligence: PercentileStat = Field(
        validation_alias=_alias_choices("intelligence")
    )
    power: PercentileStat = Field(validation_alias=_alias_choices("power"))
    education: PercentileStat = Field(validation_alias=_alias_choices("education"))
    luck: LuckStat | None = Field(
        default=None, validation_alias=_alias_choices("luck")
    )
    cthulhu_mythos: CthulhuMythos = Field(
        default=0, validation_alias=_alias_choices("cthulhu_mythos")
    )

    @model_validator(mode="before")
    @classmethod
    def _drop_empty_values(cls, data: object) -> object:
        if not isinstance(data, Mapping):
            return data

        return {
            key: value
            for key, value in data.items()
            if value not in (None, "")
        }


@validate_call
def build_investigator_card(
    *,
    name: Name,
    age: Age,
    strength: PercentileStat,
    constitution: PercentileStat,
    size: PercentileStat,
    dexterity: PercentileStat,
    appearance: PercentileStat,
    intelligence: PercentileStat,
    power: PercentileStat,
    education: PercentileStat,
    occupation: Occupation = "",
    player: Player = "",
    luck: LuckStat | None = None,
    cthulhu_mythos: CthulhuMythos = 0,
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
    parsed = InvestigatorBuildPayload.model_validate(payload)
    return build_investigator_card(
        name=parsed.name,
        player=parsed.player,
        occupation=parsed.occupation,
        age=parsed.age,
        strength=parsed.strength,
        constitution=parsed.constitution,
        size=parsed.size,
        dexterity=parsed.dexterity,
        appearance=parsed.appearance,
        intelligence=parsed.intelligence,
        power=parsed.power,
        education=parsed.education,
        luck=parsed.luck,
        cthulhu_mythos=parsed.cthulhu_mythos,
    )

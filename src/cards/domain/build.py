from __future__ import annotations

from collections.abc import Mapping, Sequence
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
from cards.domain.skills import (
    InvestigatorSkill,
    SkillKey,
    SkillName,
    SkillTemplate,
    SkillValue,
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


class InvestigatorSkillInput(BaseModel):
    """用于挂载到调查员卡的技能输入。"""

    model_config = ConfigDict(extra="forbid")

    template_key: SkillKey
    branch_key: SkillKey | None = None
    branch_name: SkillName | None = None
    value: SkillValue | None = None


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
    luck: LuckStat | None = Field(default=None, validation_alias=_alias_choices("luck"))
    cthulhu_mythos: CthulhuMythos = Field(
        default=0, validation_alias=_alias_choices("cthulhu_mythos")
    )
    skills: list[InvestigatorSkillInput] = Field(
        default_factory=list,
        validation_alias=AliasChoices("skills", "技能"),
    )

    @model_validator(mode="before")
    @classmethod
    def _drop_empty_values(cls, data: object) -> object:
        if not isinstance(data, Mapping):
            return data

        return {key: value for key, value in data.items() if value not in (None, "")}


def _parse_skill_inputs(
    *,
    payload_skill_inputs: Sequence[InvestigatorSkillInput],
    skill_inputs: Sequence[InvestigatorSkillInput | Mapping[str, Any]] | None,
) -> list[InvestigatorSkillInput]:
    if skill_inputs is None:
        return list(payload_skill_inputs)
    return [
        item
        if isinstance(item, InvestigatorSkillInput)
        else InvestigatorSkillInput.model_validate(item)
        for item in skill_inputs
    ]


def _build_skills(
    *,
    skill_inputs: Sequence[InvestigatorSkillInput],
    skill_templates: Mapping[SkillKey, SkillTemplate] | None,
) -> dict[SkillKey, InvestigatorSkill]:
    if not skill_inputs:
        return {}
    if skill_templates is None:
        raise ValueError("提供技能输入时必须传入 skill_templates")

    skills: dict[SkillKey, InvestigatorSkill] = {}
    for input_item in skill_inputs:
        template = skill_templates.get(input_item.template_key)
        if template is None:
            raise ValueError(f"未知技能模板: {input_item.template_key}")

        resolved_definition = template.resolve(
            branch_key=input_item.branch_key,
            branch_name=input_item.branch_name,
        )
        if resolved_definition.key in skills:
            raise ValueError(f"重复的技能 key: {resolved_definition.key}")

        resolved_value = (
            resolved_definition.base
            if input_item.value is None
            else input_item.value
        )
        skills[resolved_definition.key] = InvestigatorSkill(
            definition=resolved_definition,
            value=resolved_value,
        )
    return skills


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
    skill_templates: Mapping[SkillKey, SkillTemplate] | None = None,
    skill_inputs: Sequence[InvestigatorSkillInput | Mapping[str, Any]] | None = None,
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
    parsed_skill_inputs = _parse_skill_inputs(
        payload_skill_inputs=(),
        skill_inputs=skill_inputs,
    )
    skills = _build_skills(
        skill_inputs=parsed_skill_inputs,
        skill_templates=skill_templates,
    )

    return InvestigatorCard.create(
        name=name,
        age=age,
        attributes=attributes,
        occupation=occupation,
        player=player,
        cthulhu_mythos=cthulhu_mythos,
        skills=skills,
    )


def build_investigator_from_mapping(
    payload: Mapping[str, Any],
    *,
    skill_templates: Mapping[SkillKey, SkillTemplate] | None = None,
    skill_inputs: Sequence[InvestigatorSkillInput | Mapping[str, Any]] | None = None,
) -> InvestigatorCard:
    parsed = InvestigatorBuildPayload.model_validate(payload)
    parsed_skill_inputs = _parse_skill_inputs(
        payload_skill_inputs=parsed.skills,
        skill_inputs=skill_inputs,
    )
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
        skill_templates=skill_templates,
        skill_inputs=parsed_skill_inputs,
    )

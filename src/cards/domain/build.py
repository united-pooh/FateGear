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


def _expand_base_skills(
    skill_templates: Mapping[SkillKey, SkillTemplate],
) -> dict[SkillKey, InvestigatorSkill]:
    """将模板库中所有「确定性技能」展开为以基础值初始化的技能映射。

    「确定性技能」定义：
    - 非分支技能（branch_mode=none）：直接具体化，key 就是 template.key。
    - 有预定义 branch_options 的分支技能：每个 option 各自具体化，
      key 形如 ``template_key:branch_key``。

    ``allow_custom_branch=True`` 且无预定义 branch_options 的纯自定义分支技能
    （如 language_other）不在此展开——它们必须在 skill_inputs 里显式提供。
    """
    skills: dict[SkillKey, InvestigatorSkill] = {}
    for template in skill_templates.values():
        if not template.is_branch_skill:
            definition = template.resolve()
            skills[definition.key] = InvestigatorSkill(
                definition=definition,
                value=definition.base,
            )
        elif template.branch_options:
            for option in template.branch_options:
                definition = template.resolve(
                    branch_key=option.key,
                    branch_name=option.name,
                )
                skills[definition.key] = InvestigatorSkill(
                    definition=definition,
                    value=definition.base,
                )
        # else: 纯自定义分支技能，跳过，由 skill_inputs 提供
    return skills


def _build_skills(
    *,
    skill_inputs: Sequence[InvestigatorSkillInput],
    skill_templates: Mapping[SkillKey, SkillTemplate] | None,
    fill_base_skills: bool = False,
) -> dict[SkillKey, InvestigatorSkill]:
    if fill_base_skills and skill_templates is None:
        raise ValueError("fill_base_skills=True 时必须传入 skill_templates")

    skills: dict[SkillKey, InvestigatorSkill] = {}

    if fill_base_skills and skill_templates is not None:
        skills = _expand_base_skills(skill_templates)

    if not skill_inputs:
        return skills

    if skill_templates is None:
        raise ValueError("提供技能输入时必须传入 skill_templates")

    explicit_keys: set[SkillKey] = set()
    for input_item in skill_inputs:
        template = skill_templates.get(input_item.template_key)
        if template is None:
            raise ValueError(f"未知技能模板: {input_item.template_key}")

        resolved_definition = template.resolve(
            branch_key=input_item.branch_key,
            branch_name=input_item.branch_name,
        )
        if resolved_definition.key in explicit_keys:
            raise ValueError(f"重复的技能 key: {resolved_definition.key}")
        explicit_keys.add(resolved_definition.key)

        resolved_value = (
            resolved_definition.base if input_item.value is None else input_item.value
        )
        # skill_inputs 中显式指定的条目覆盖 fill_base_skills 的默认值
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
    fill_base_skills: bool = False,
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
        fill_base_skills=fill_base_skills,
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
    fill_base_skills: bool = False,
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
        fill_base_skills=fill_base_skills,
    )

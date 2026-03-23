from __future__ import annotations

from enum import StrEnum
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, computed_field, model_validator

SkillKey = Annotated[
    str,
    Field(
        min_length=1,
        max_length=50,
        pattern=r"^[a-z][a-z0-9_]*(?::[a-z][a-z0-9_]*)?$",
    ),
]
SkillName = Annotated[str, Field(min_length=1, max_length=30)]
SkillBase = Annotated[int, Field(ge=0, le=99, strict=True)]
BranchLabel = Annotated[str, Field(min_length=1, max_length=20)]


class SkillBranchMode(StrEnum):
    NONE = "none"
    REQUIRED = "required"


class SkillBranchOption(BaseModel):
    """分支技能的一个可选分支，例如“化学”或“摄影”."""

    model_config = ConfigDict(frozen=True)

    key: SkillKey
    name: SkillName


class SkillDefinition(BaseModel):
    """已经具体化后的技能定义，可直接给职业模板或角色卡引用。"""

    model_config = ConfigDict(frozen=True)

    key: SkillKey
    name: SkillName
    base: SkillBase
    template_key: SkillKey
    branch_key: SkillKey | None = None
    branch_name: SkillName | None = None

    @computed_field
    @property
    def is_branch_skill(self) -> bool:
        return self.branch_key is not None

    @model_validator(mode="after")
    def _validate_branch_pair(self) -> "SkillDefinition":
        has_branch_key = self.branch_key is not None
        has_branch_name = self.branch_name is not None
        if has_branch_key != has_branch_name:
            raise ValueError("branch_key and branch_name must be provided together")
        return self


class SkillTemplate(BaseModel):
    """技能模板，描述基础值以及是否要求额外的分支名。"""

    model_config = ConfigDict(frozen=True)

    key: SkillKey
    name: SkillName
    base: SkillBase
    branch_mode: SkillBranchMode = SkillBranchMode.NONE
    branch_label: BranchLabel | None = None
    allow_custom_branch: bool = False
    branch_options: tuple[SkillBranchOption, ...] = ()

    @computed_field
    @property
    def is_branch_skill(self) -> bool:
        return self.branch_mode is SkillBranchMode.REQUIRED

    @model_validator(mode="after")
    def _validate_branch_shape(self) -> "SkillTemplate":
        if self.branch_mode is SkillBranchMode.NONE:
            if self.branch_label is not None:
                raise ValueError("branch_label is only allowed for branch skills")
            if self.allow_custom_branch:
                raise ValueError("allow_custom_branch requires a branch skill")
            if self.branch_options:
                raise ValueError("branch_options are only allowed for branch skills")
            return self

        if self.branch_label is None:
            raise ValueError("branch_label is required for branch skills")
        if not self.allow_custom_branch and not self.branch_options:
            raise ValueError(
                "branch skills must define branch_options or allow_custom_branch"
            )

        option_keys = [option.key for option in self.branch_options]
        if len(option_keys) != len(set(option_keys)):
            raise ValueError("branch option keys must be unique")

        option_names = [option.name for option in self.branch_options]
        if len(option_names) != len(set(option_names)):
            raise ValueError("branch option names must be unique")

        return self

    def resolve(
        self,
        *,
        branch_key: SkillKey | None = None,
        branch_name: SkillName | None = None,
    ) -> SkillDefinition:
        if not self.is_branch_skill:
            if branch_key is not None or branch_name is not None:
                raise ValueError("branch arguments are only allowed for branch skills")
            return SkillDefinition(
                key=self.key,
                name=self.name,
                base=self.base,
                template_key=self.key,
            )

        matched_by_key = None
        if branch_key is not None:
            matched_by_key = next(
                (
                    option
                    for option in self.branch_options
                    if option.key == branch_key
                ),
                None,
            )
            if matched_by_key is not None and (
                branch_name is not None and matched_by_key.name != branch_name
            ):
                raise ValueError("branch_name does not match branch_key")

        matched_by_name = None
        if branch_name is not None:
            matched_by_name = next(
                (
                    option
                    for option in self.branch_options
                    if option.name == branch_name
                ),
                None,
            )
            if matched_by_key is not None and (
                matched_by_name is not None and matched_by_name.key != matched_by_key.key
            ):
                raise ValueError("branch_key and branch_name reference different options")

        matched_option = matched_by_key or matched_by_name
        if matched_option is not None:
            branch_key = matched_option.key
            branch_name = matched_option.name
        else:
            if not self.allow_custom_branch:
                raise ValueError(
                    "branch skill must use one of the predefined branch options"
                )
            if branch_key is None or branch_name is None:
                raise ValueError(
                    "custom branch skills require both branch_key and branch_name"
                )

        return SkillDefinition(
            key=f"{self.key}:{branch_key}",
            name=f"{self.name}({branch_name})",
            base=self.base,
            template_key=self.key,
            branch_key=branch_key,
            branch_name=branch_name,
        )

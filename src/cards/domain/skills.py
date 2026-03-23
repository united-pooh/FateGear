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
            raise ValueError("branch_key 和 branch_name 必须同时提供")
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
                raise ValueError("branch_label 只能用于分支技能")
            if self.allow_custom_branch:
                raise ValueError("allow_custom_branch 只能用于分支技能")
            if self.branch_options:
                raise ValueError("branch_options 只能用于分支技能")
            return self

        if self.branch_label is None:
            raise ValueError("分支技能必须提供 branch_label")
        if not self.allow_custom_branch and not self.branch_options:
            raise ValueError(
                "分支技能必须定义 branch_options，或启用 allow_custom_branch"
            )

        option_keys = [option.key for option in self.branch_options]
        if len(option_keys) != len(set(option_keys)):
            raise ValueError("分支选项的 key 必须唯一")

        option_names = [option.name for option in self.branch_options]
        if len(option_names) != len(set(option_names)):
            raise ValueError("分支选项的 name 必须唯一")

        return self

    def resolve(
        self,
        *,
        branch_key: SkillKey | None = None,
        branch_name: SkillName | None = None,
    ) -> SkillDefinition:
        if not self.is_branch_skill:
            if branch_key is not None or branch_name is not None:
                raise ValueError("只有分支技能才允许传入 branch 参数")
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
                raise ValueError("branch_name 与 branch_key 不匹配")

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
                raise ValueError("branch_key 和 branch_name 指向了不同的分支选项")

        matched_option = matched_by_key or matched_by_name
        if matched_option is not None:
            branch_key = matched_option.key
            branch_name = matched_option.name
        else:
            if not self.allow_custom_branch:
                raise ValueError(
                    "该分支技能必须使用预定义的分支选项之一"
                )
            if branch_key is None or branch_name is None:
                raise ValueError(
                    "自定义分支技能必须同时提供 branch_key 和 branch_name"
                )

        return SkillDefinition(
            key=f"{self.key}:{branch_key}",
            name=f"{self.name}({branch_name})",
            base=self.base,
            template_key=self.key,
            branch_key=branch_key,
            branch_name=branch_name,
        )

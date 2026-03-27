from __future__ import annotations

from collections.abc import Callable, Hashable, Iterable
from typing import TypeVar

from cards.domain.skills import SkillDefinition, SkillTemplate

_T = TypeVar("_T")


def _validate_unique_values(
    items: Iterable[_T],
    *,
    value_getter: Callable[[_T], Hashable],
    label: str,
) -> None:
    seen: set[Hashable] = set()

    for item in items:
        value = value_getter(item)
        if value in seen:
            raise ValueError(f"{label} 必须唯一: {value}")
        seen.add(value)


def validate_skill_templates(templates: Iterable[SkillTemplate]) -> None:
    """校验技能模板集合层面的唯一性与一致性。"""

    template_list = tuple(templates)
    _validate_unique_values(
        template_list,
        value_getter=lambda template: template.key,
        label="技能模板 key",
    )
    _validate_unique_values(
        template_list,
        value_getter=lambda template: template.name,
        label="技能模板 name",
    )


def validate_skill_definitions(definitions: Iterable[SkillDefinition]) -> None:
    """校验已具体化技能定义集合层面的唯一性与一致性。"""

    definition_list = tuple(definitions)
    _validate_unique_values(
        definition_list,
        value_getter=lambda definition: definition.key,
        label="技能定义 key",
    )

    seen_materializations: set[tuple[str, str | None]] = set()
    for definition in definition_list:
        materialization = (definition.template_key, definition.branch_key)
        if materialization in seen_materializations:
            if definition.branch_key is None:
                raise ValueError(
                    "技能定义不能重复引用同一个 template_key: "
                    f"{definition.template_key}"
                )
            raise ValueError(
                "同一模板下的分支技能不能重复具体化: "
                f"{definition.template_key}:{definition.branch_key}"
            )
        seen_materializations.add(materialization)


__all__ = ["validate_skill_definitions", "validate_skill_templates"]

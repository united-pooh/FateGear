from __future__ import annotations

import json
from pathlib import Path

from cards.domain.skills import SkillTemplate
from cards.rules.validation import validate_skill_templates
from cards.seed import BASE_SKILLS_PATH, BRANCH_SKILLS_PATH


def _load_skill_templates_from_path(path: str | Path) -> tuple[SkillTemplate, ...]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(payload, list):
        raise ValueError(f"技能模板种子必须是数组: {path}")

    templates = tuple(
        SkillTemplate.model_validate(item) for item in payload if isinstance(item, dict)
    )
    if len(templates) != len(payload):
        raise ValueError(f"技能模板种子中存在非法条目: {path}")

    validate_skill_templates(templates)
    return templates


def load_base_skill_templates(
    path: str | Path | None = None,
) -> tuple[SkillTemplate, ...]:
    target = path or BASE_SKILLS_PATH
    return _load_skill_templates_from_path(target)


def load_branch_skill_templates(
    path: str | Path | None = None,
) -> tuple[SkillTemplate, ...]:
    target = path or BRANCH_SKILLS_PATH
    return _load_skill_templates_from_path(target)


def load_skill_templates(
    *,
    base_path: str | Path | None = None,
    branch_path: str | Path | None = None,
) -> tuple[SkillTemplate, ...]:
    templates = (
        *load_base_skill_templates(base_path),
        *load_branch_skill_templates(branch_path),
    )
    validate_skill_templates(templates)
    return templates


def load_skill_template_mapping(
    *,
    base_path: str | Path | None = None,
    branch_path: str | Path | None = None,
) -> dict[str, SkillTemplate]:
    return {
        template.key: template
        for template in load_skill_templates(
            base_path=base_path,
            branch_path=branch_path,
        )
    }


__all__ = [
    "load_base_skill_templates",
    "load_branch_skill_templates",
    "load_skill_template_mapping",
    "load_skill_templates",
]

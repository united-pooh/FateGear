from __future__ import annotations

import pytest

from cards.domain.skills import (
    SkillBranchMode,
    SkillBranchOption,
    SkillDefinition,
    SkillTemplate,
)
from cards.rules.validation import validate_skill_definitions, validate_skill_templates


def _make_science_template() -> SkillTemplate:
    return SkillTemplate(
        key="science",
        name="科学",
        base=1,
        branch_mode=SkillBranchMode.REQUIRED,
        branch_label="学科",
        branch_options=(
            SkillBranchOption(key="chemistry", name="化学"),
            SkillBranchOption(key="physics", name="物理"),
        ),
    )


def test_validate_skill_templates_accepts_unique_templates() -> None:
    validate_skill_templates(
        (
            SkillTemplate(key="listen", name="聆听", base=20),
            _make_science_template(),
        )
    )


def test_validate_skill_templates_rejects_duplicate_keys() -> None:
    with pytest.raises(ValueError, match="技能模板 key 必须唯一"):
        validate_skill_templates(
            (
                SkillTemplate(key="listen", name="聆听", base=20),
                SkillTemplate(key="listen", name="侦查", base=25),
            )
        )


def test_validate_skill_templates_rejects_duplicate_names() -> None:
    with pytest.raises(ValueError, match="技能模板 name 必须唯一"):
        validate_skill_templates(
            (
                SkillTemplate(key="listen", name="聆听", base=20),
                SkillTemplate(key="spot_hidden", name="聆听", base=25),
            )
        )


def test_validate_skill_definitions_accepts_unique_definitions() -> None:
    template = _make_science_template()

    validate_skill_definitions(
        (
            SkillTemplate(key="listen", name="聆听", base=20).resolve(),
            template.resolve(branch_key="chemistry"),
            template.resolve(branch_key="physics"),
        )
    )


def test_validate_skill_definitions_rejects_duplicate_keys() -> None:
    definition = _make_science_template().resolve(branch_key="chemistry")

    with pytest.raises(ValueError, match="技能定义 key 必须唯一"):
        validate_skill_definitions((definition, definition.model_copy()))


def test_validate_skill_definitions_rejects_duplicate_materializations() -> None:
    chemistry = _make_science_template().resolve(branch_key="chemistry")
    duplicate_materialization = SkillDefinition(
        key="science:chemistry_alt",
        name="科学(化学复写)",
        base=1,
        template_key="science",
        branch_key="chemistry",
        branch_name="化学",
    )

    with pytest.raises(ValueError, match="同一模板下的分支技能不能重复具体化"):
        validate_skill_definitions((chemistry, duplicate_materialization))

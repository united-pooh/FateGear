from __future__ import annotations

import pytest
from pydantic import ValidationError

from cards.domain.skills import (
    SkillBranchMode,
    SkillBranchOption,
    SkillTemplate,
)


def test_regular_skill_template_rejects_branch_metadata() -> None:
    with pytest.raises(ValidationError):
        SkillTemplate(
            key="listen",
            name="聆听",
            base=20,
            branch_label="学科",
        )


def test_branch_skill_template_requires_branch_source() -> None:
    with pytest.raises(ValidationError):
        SkillTemplate(
            key="science",
            name="科学",
            base=1,
            branch_mode=SkillBranchMode.REQUIRED,
            branch_label="学科",
        )


def test_resolve_regular_skill_definition() -> None:
    template = SkillTemplate(key="listen", name="聆听", base=20)

    resolved = template.resolve()

    assert resolved.key == "listen"
    assert resolved.name == "聆听"
    assert resolved.base == 20
    assert resolved.template_key == "listen"
    assert resolved.is_branch_skill is False


def test_resolve_predefined_branch_skill_by_key() -> None:
    template = SkillTemplate(
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

    resolved = template.resolve(branch_key="chemistry")

    assert resolved.key == "science:chemistry"
    assert resolved.name == "科学(化学)"
    assert resolved.branch_key == "chemistry"
    assert resolved.branch_name == "化学"
    assert resolved.is_branch_skill is True


def test_resolve_branch_skill_rejects_unknown_predefined_branch() -> None:
    template = SkillTemplate(
        key="science",
        name="科学",
        base=1,
        branch_mode=SkillBranchMode.REQUIRED,
        branch_label="学科",
        branch_options=(SkillBranchOption(key="chemistry", name="化学"),),
    )

    with pytest.raises(ValueError):
        template.resolve(branch_key="biology", branch_name="生物学")


def test_resolve_custom_branch_skill_requires_key_and_name() -> None:
    template = SkillTemplate(
        key="art_craft",
        name="艺术/手艺",
        base=5,
        branch_mode=SkillBranchMode.REQUIRED,
        branch_label="门类",
        allow_custom_branch=True,
    )

    with pytest.raises(ValueError):
        template.resolve(branch_name="摄影")

    resolved = template.resolve(branch_key="photography", branch_name="摄影")

    assert resolved.key == "art_craft:photography"
    assert resolved.name == "艺术/手艺(摄影)"

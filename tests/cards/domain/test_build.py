from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from cards.domain.build import build_investigator_from_mapping
from cards.domain.build import build_investigator_card
from cards.domain.skills import SkillBranchMode, SkillBranchOption, SkillTemplate


def _load_fixture_payload() -> dict[str, object]:
    fixture_path = (
        Path(__file__).resolve().parents[1] / "fixtures" / "investigator_minimal.json"
    )
    return json.loads(fixture_path.read_text(encoding="utf-8"))


def test_build_investigator_from_mapping_fixture() -> None:
    payload = _load_fixture_payload()

    card = build_investigator_from_mapping(payload)

    assert card.name == "前原树一"
    assert card.occupation == "大学生"
    assert card.player == "黑色通缉令"
    assert card.derived.hit_points_max == 11
    assert card.derived.magic_points_max == 10
    assert card.derived.starting_sanity == 50
    assert card.derived.sanity_max == 99
    assert card.derived.move_rate == 9
    assert card.derived.build == 1
    assert card.derived.damage_bonus.notation == "+1D4"
    assert card.state.hit_points == 11
    assert card.state.magic_points == 10
    assert card.state.sanity == 50


@pytest.mark.parametrize("invalid_age", ["20", 20.0, True])
def test_build_investigator_from_mapping_rejects_non_strict_age(
    invalid_age: object,
) -> None:
    payload = _load_fixture_payload()
    payload["年龄"] = invalid_age

    with pytest.raises(ValidationError):
        build_investigator_from_mapping(payload)


def _base_build_kwargs() -> dict[str, object]:
    return {
        "name": "测试员",
        "age": 20,
        "strength": 50,
        "constitution": 60,
        "size": 60,
        "dexterity": 50,
        "appearance": 50,
        "intelligence": 50,
        "power": 60,
        "education": 50,
    }


def test_build_investigator_card_mounts_regular_skill() -> None:
    templates = {"listen": SkillTemplate(key="listen", name="聆听", base=20)}

    card = build_investigator_card(
        **_base_build_kwargs(),
        skill_templates=templates,
        skill_inputs=[{"template_key": "listen", "value": 65}],
    )

    assert "listen" in card.skills
    assert card.skills["listen"].value == 65
    assert card.skills["listen"].definition.template_key == "listen"


def test_build_investigator_card_mounts_branch_skill() -> None:
    templates = {
        "science": SkillTemplate(
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
    }

    card = build_investigator_card(
        **_base_build_kwargs(),
        skill_templates=templates,
        skill_inputs=[{"template_key": "science", "branch_key": "chemistry"}],
    )

    assert "science:chemistry" in card.skills
    assert card.skills["science:chemistry"].definition.branch_name == "化学"
    assert card.skills["science:chemistry"].value == 1


def test_build_investigator_card_defaults_skill_value_to_definition_base() -> None:
    templates = {"listen": SkillTemplate(key="listen", name="聆听", base=20)}

    card = build_investigator_card(
        **_base_build_kwargs(),
        skill_templates=templates,
        skill_inputs=[{"template_key": "listen"}],
    )

    assert card.skills["listen"].value == 20


def test_build_investigator_card_rejects_duplicate_resolved_skill_key() -> None:
    templates = {"listen": SkillTemplate(key="listen", name="聆听", base=20)}

    with pytest.raises(ValueError, match="重复的技能 key: listen"):
        build_investigator_card(
            **_base_build_kwargs(),
            skill_templates=templates,
            skill_inputs=[
                {"template_key": "listen", "value": 30},
                {"template_key": "listen", "value": 40},
            ],
        )


def test_build_investigator_card_rejects_unknown_skill_template_key() -> None:
    templates = {"listen": SkillTemplate(key="listen", name="聆听", base=20)}

    with pytest.raises(ValueError, match="未知技能模板: stealth"):
        build_investigator_card(
            **_base_build_kwargs(),
            skill_templates=templates,
            skill_inputs=[{"template_key": "stealth", "value": 30}],
        )


def test_build_investigator_from_mapping_supports_payload_skills() -> None:
    templates = {"listen": SkillTemplate(key="listen", name="聆听", base=20)}
    payload = _load_fixture_payload()
    payload["skills"] = [{"template_key": "listen"}]

    card = build_investigator_from_mapping(payload, skill_templates=templates)

    assert card.skills["listen"].value == 20


def test_build_investigator_from_mapping_supports_optional_skill_inputs_arg() -> None:
    templates = {"listen": SkillTemplate(key="listen", name="聆听", base=20)}
    payload = _load_fixture_payload()

    card = build_investigator_from_mapping(
        payload,
        skill_templates=templates,
        skill_inputs=[{"template_key": "listen", "value": 55}],
    )

    assert card.skills["listen"].value == 55

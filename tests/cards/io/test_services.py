from __future__ import annotations

from cards.io import (
    load_base_skill_templates,
    load_branch_skill_templates,
    load_skill_template_mapping,
    load_skill_templates,
)
from cards.rules.validation import validate_skill_templates


def test_load_base_skill_templates_reads_regular_templates() -> None:
    templates = load_base_skill_templates()

    assert templates
    template_by_key = {template.key: template for template in templates}
    assert "listen" in template_by_key
    assert template_by_key["listen"].name == "聆听"
    assert template_by_key["listen"].base == 20
    assert template_by_key["listen"].is_branch_skill is False
    validate_skill_templates(templates)


def test_load_branch_skill_templates_reads_branch_templates() -> None:
    templates = load_branch_skill_templates()

    assert templates
    template_by_key = {template.key: template for template in templates}
    assert "science" in template_by_key
    assert template_by_key["science"].is_branch_skill is True
    assert template_by_key["science"].branch_label == "学科"
    assert template_by_key["science"].branch_options
    validate_skill_templates(templates)


def test_load_skill_templates_and_mapping_are_valid() -> None:
    templates = load_skill_templates()
    template_mapping = load_skill_template_mapping()

    assert templates
    assert template_mapping
    assert set(template_mapping) == {template.key for template in templates}
    validate_skill_templates(templates)

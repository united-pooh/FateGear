from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from cards.domain.build import build_investigator_from_mapping


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

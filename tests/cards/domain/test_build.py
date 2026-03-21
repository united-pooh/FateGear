from __future__ import annotations

import json
from pathlib import Path

from cards.domain.build import build_investigator_from_mapping


def test_build_investigator_from_mapping_fixture() -> None:
    fixture_path = Path(__file__).resolve().parents[1] / "fixtures" / "investigator_minimal.json"
    payload = json.loads(fixture_path.read_text(encoding="utf-8"))

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

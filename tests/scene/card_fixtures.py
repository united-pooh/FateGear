from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable

from cards import build_investigator_from_mapping, load_skill_template_mapping
from cards.domain.card import InvestigatorCard

_FIXTURE_PATH = (
    Path(__file__).resolve().parents[1]
    / "cards"
    / "fixtures"
    / "investigator_minimal.json"
)
_SKILL_TEMPLATES = load_skill_template_mapping()
_DEFAULT_SKILL_INPUTS: list[dict[str, object]] = [
    {"template_key": "spot_hidden", "value": 80},
    {"template_key": "stealth", "value": 70},
    {"template_key": "first_aid", "value": 65},
    {
        "template_key": "art_craft",
        "branch_key": "locksmith",
        "branch_name": "锁匠",
        "value": 70,
    },
    {
        "template_key": "science",
        "branch_key": "physics",
        "value": 75,
    },
]


def _load_payload() -> dict[str, object]:
    return json.loads(_FIXTURE_PATH.read_text(encoding="utf-8"))


def build_test_card(
    player_id: str,
    *,
    skill_inputs: list[dict[str, object]] | None = None,
) -> InvestigatorCard:
    payload = _load_payload()
    payload["玩家"] = player_id
    payload["姓名"] = f"测试调查员-{player_id}"
    return build_investigator_from_mapping(
        payload,
        skill_templates=_SKILL_TEMPLATES,
        skill_inputs=skill_inputs or _DEFAULT_SKILL_INPUTS,
    )


def build_player_cards(player_ids: Iterable[str]) -> dict[str, InvestigatorCard]:
    return {
        player_id: build_test_card(player_id)
        for player_id in player_ids
    }

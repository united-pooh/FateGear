from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest

from cards import build_investigator_from_mapping, load_skill_template_mapping
from scenario.runtime import SceneRuntime, TurnResolution

from tests.scene.card_fixtures import build_player_cards


def _load_investigator_payload() -> dict[str, object]:
    fixture = (
        Path(__file__).resolve().parents[1]
        / "cards"
        / "fixtures"
        / "investigator_minimal.json"
    )
    return json.loads(fixture.read_text(encoding="utf-8"))


def _submit_and_resolve(
    runtime: SceneRuntime,
    *,
    session_id: str,
    intents: dict[str, dict[str, object]],
) -> TurnResolution:
    for player_id, intent in intents.items():
        runtime.submit_intent(session_id, player_id, intent)
    return asyncio.run(runtime.resolve_turn(session_id))


def test_action_check_failure_does_not_apply_success_effects() -> None:
    card = build_investigator_from_mapping(
        _load_investigator_payload(),
        skill_templates=load_skill_template_mapping(),
        skill_inputs=[{"template_key": "spot_hidden", "value": 10}],
    )
    runtime = SceneRuntime(roll_provider=lambda: 90)
    session = runtime.create_session(
        "generic_mvp",
        ["p1"],
        player_cards={"p1": card},
    )

    _submit_and_resolve(
        runtime,
        session_id=session.session_id,
        intents={"p1": {"type": "move", "target_scene_id": "storage"}},
    )
    resolution = _submit_and_resolve(
        runtime,
        session_id=session.session_id,
        intents={"p1": {"type": "action", "action_id": "find_key"}},
    )
    outcome = resolution.scene_batches[0].outcomes[0]

    assert outcome.success is False
    assert outcome.reason == "你没有在杂物中找到任何钥匙线索。"
    assert "key_found" not in session.global_flags
    assert "find_key" not in session.completed_actions
    assert len(resolution.dice_rolls) == 1
    roll = resolution.dice_rolls[0]
    assert roll.source == "static_action_check"
    assert roll.turn_no == 2
    assert roll.player_id == "p1"
    assert roll.action_id == "find_key"
    assert roll.action_name == "搜索钥匙"
    assert roll.skill_key == "spot_hidden"
    assert roll.roll_value == 90
    assert roll.threshold == 10
    assert roll.success is False
    assert roll.success_level == "fail"


def test_create_session_requires_player_cards_for_all_players() -> None:
    runtime = SceneRuntime()

    with pytest.raises(TypeError):
        runtime.create_session("generic_mvp", ["p1"])

    with pytest.raises(ValueError, match="缺少玩家"):
        runtime.create_session(
            "generic_mvp",
            ["p1", "p2"],
            player_cards=build_player_cards(["p1"]),
        )


def test_add_player_supports_investigator_card_injection() -> None:
    card = build_investigator_from_mapping(
        _load_investigator_payload(),
        skill_templates=load_skill_template_mapping(),
        skill_inputs=[{"template_key": "spot_hidden", "value": 55}],
    )
    runtime = SceneRuntime()
    session = runtime.create_session(
        "generic_mvp",
        ["host"],
        player_cards=build_player_cards(["host"]),
    )

    player_state = runtime.add_player(
        session.session_id,
        "p2",
        investigator=card,
    )

    assert player_state.investigator is not None
    assert player_state.investigator is not card
    assert player_state.investigator.name == card.name


def test_add_player_requires_investigator_card() -> None:
    runtime = SceneRuntime()
    session = runtime.create_session(
        "generic_mvp",
        ["host"],
        player_cards=build_player_cards(["host"]),
    )

    with pytest.raises(TypeError):
        runtime.add_player(session.session_id, "p2")

    with pytest.raises(ValueError, match="必须提供 investigator"):
        runtime.add_player(
            session.session_id,
            "p2",
            investigator=None,
        )

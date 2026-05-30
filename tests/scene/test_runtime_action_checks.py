from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

from cards import build_investigator_from_mapping, load_skill_template_mapping
from scenario.agent.models import KeeperAgentPlan, ProposedCheck
from scenario.runtime import SceneRuntime, TurnResolution

from tests.scene.card_fixtures import build_player_cards


@dataclass
class _Meta:
    fallback_used: bool = False
    model_id: str = "fake-freeform-planner"


@dataclass
class _Record:
    prompt: Any
    output: Any
    meta: _Meta = field(default_factory=_Meta)


class _FreeformCheckPlanner:
    def __init__(self) -> None:
        self.records: list[_Record] = []

    async def call(self, prompt: Any) -> _Record:
        checks: list[ProposedCheck] = []
        for intent in prompt.pending_intents:
            if intent.intent_type != "freeform":
                continue
            checks.append(
                ProposedCheck(
                    player_id=intent.player_id,
                    action_id="freeform",
                    skill_key="spot_hidden",
                    proposed_difficulty="hard",
                    rationale="玩家正在违背安全直觉接近未知声源，需要侦查裁定风险。",
                )
            )
        record = _Record(
            prompt=prompt,
            output=KeeperAgentPlan(
                intent_summary="自由行动动态检定测试",
                proposed_checks=checks,
                keeper_notes="不要把自由行动改写成菜单动作。",
            ),
        )
        self.records.append(record)
        return record


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


def test_freeform_intent_can_receive_dynamic_check_without_advancing_story() -> None:
    planner = _FreeformCheckPlanner()
    runtime = SceneRuntime(roll_provider=lambda: 1, plan_agent=planner)
    session = runtime.create_session(
        "tokoyami_subset",
        ["p1"],
        player_cards=build_player_cards(["p1"]),
    )

    resolution = _submit_and_resolve(
        runtime,
        session_id=session.session_id,
        intents={
            "p1": {
                "type": "freeform",
                "text": "我偏要往后方声音来源走过去看看",
            }
        },
    )
    outcome = resolution.scene_batches[0].outcomes[0]

    assert planner.records[0].prompt.pending_intents[0].intent_type == "freeform"
    assert planner.records[0].prompt.pending_intents[0].freeform_text == (
        "我偏要往后方声音来源走过去看看"
    )
    assert outcome.intent_type == "freeform"
    assert outcome.success is True
    assert outcome.freeform_text == "我偏要往后方声音来源走过去看看"
    assert outcome.effects_applied == []
    assert session.player_states["p1"].current_scene_id == "car_6"
    assert session.story_state.current_stage_id == "awake"
    assert resolution.applied_story_transition_id is None
    assert session.completed_actions == set()
    assert len(resolution.dice_rolls) == 1
    roll = resolution.dice_rolls[0]
    assert roll.source == "dynamic_agent_check"
    assert roll.action_id == "freeform"
    assert roll.skill_key == "spot_hidden"
    assert roll.roll_value == 1
    assert roll.success is True


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

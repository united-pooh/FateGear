from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import pytest

from cards import build_investigator_from_mapping, load_skill_template_mapping
from scenario.agent.models import KeeperAgentPlan, ProposedCheck, ProposedEffect
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


class _OffMapBoundaryPlanner:
    def __init__(self) -> None:
        self.records: list[_Record] = []

    async def call(self, prompt: Any) -> _Record:
        record = _Record(
            prompt=prompt,
            output=KeeperAgentPlan(
                intent_summary="玩家尝试前往地图外危险边界。",
                proposed_checks=[
                    ProposedCheck(
                        player_id="p1",
                        action_id="freeform",
                        skill_key="spot_hidden",
                        proposed_difficulty="hard",
                        rationale="七号车厢不在场景图中，接近后方威胁边界。",
                    )
                ],
                proposed_effects=[
                    ProposedEffect(
                        effect_type="advance_clock",
                        target_id="rear_threat",
                        value=2,
                        rationale="向七号车厢方向试探会显著吸引后方威胁。",
                    )
                ],
            ),
        )
        self.records.append(record)
        return record


class _FreeformStealthPlanner:
    def __init__(self) -> None:
        self.records: list[_Record] = []

    async def call(self, prompt: Any) -> _Record:
        record = _Record(
            prompt=prompt,
            output=KeeperAgentPlan(
                intent_summary="自由行动潜行检定测试",
                proposed_checks=[
                    ProposedCheck(
                        player_id=intent.player_id,
                        action_id="freeform",
                        skill_key="stealth",
                        proposed_difficulty="hard",
                        rationale="连续接近黑暗边界时需要压低脚步。",
                    )
                    for intent in prompt.pending_intents
                    if intent.intent_type == "freeform"
                ],
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
                "requested_skill_key": "spot_hidden",
            }
        },
    )
    outcome = resolution.scene_batches[0].outcomes[0]

    assert planner.records[0].prompt.pending_intents[0].intent_type == "freeform"
    assert planner.records[0].prompt.pending_intents[0].freeform_text == (
        "我偏要往后方声音来源走过去看看"
    )
    assert planner.records[0].prompt.pending_intents[0].requested_skill_key == (
        "spot_hidden"
    )
    assert outcome.intent_type == "freeform"
    assert outcome.success is True
    assert outcome.freeform_text == "我偏要往后方声音来源走过去看看"
    assert outcome.requested_skill_key == "spot_hidden"
    assert outcome.effects_applied == ["玩家主动检定:spot_hidden"]
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
    assert roll.success_level == "critical"
    assert roll.display_text == (
        "spot_hidden CHECK\n投掷骰子 d100=1\n目标值 80：大成功"
    )
    assert roll.success is True


def test_off_map_freeform_can_apply_agent_boundary_consequence() -> None:
    planner = _OffMapBoundaryPlanner()
    runtime = SceneRuntime(roll_provider=lambda: 99, plan_agent=planner)
    session = runtime.create_session(
        "tokoyami_subset",
        ["p1"],
        player_cards=build_player_cards(["p1"]),
    )
    session.player_states["p1"].current_scene_id = "car_4"
    session.story_state.current_stage_id = "informed"
    session.global_flags.add("note_read")

    resolution = _submit_and_resolve(
        runtime,
        session_id=session.session_id,
        intents={
            "p1": {
                "type": "freeform",
                "text": "我想尝试前往七号车厢",
                "freeform_kind": "off_map_move",
                "intended_target": "七号车厢",
                "risk_hint": "玩家正在尝试前往模组场景图未定义或当前不可达的危险边界。",
            }
        },
    )
    outcome = resolution.scene_batches[0].outcomes[0]

    assert planner.records[0].prompt.pending_intents[0].freeform_kind == (
        "off_map_move"
    )
    assert outcome.intent_type == "freeform"
    assert outcome.success is False
    assert outcome.freeform_kind == "off_map_move"
    assert outcome.intended_target == "七号车厢"
    assert session.player_states["p1"].current_scene_id == "car_4"
    assert session.story_state.current_stage_id == "informed"
    assert resolution.applied_clock_deltas["rear_threat"] == 4
    assert session.clock_values["rear_threat"] == 4
    assert [roll.source for roll in resolution.dice_rolls] == ["status_consequence"]
    assert resolution.dice_rolls[0].visibility == "keeper"
    assert resolution.dice_rolls[0].label == "SAN CHECK"
    assert resolution.dice_rolls[0].notation == "1d3"
    assert resolution.dice_rolls[0].total == 3
    assert session.player_states["p1"].investigator.state.sanity == 47
    assert "暗骰状态变化:SAN-3(50->47)" in outcome.effects_applied
    assert any(
        event.type == "agent_effects_queued"
        and event.effects_applied == ["Agent推进时钟:rear_threat+2"]
        for event in resolution.event_log
    )


def test_requested_off_map_skill_fumble_shows_rolls_and_updates_status() -> None:
    rolls = iter([100, 3])
    runtime = SceneRuntime(roll_provider=lambda: next(rolls, 99))
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
                "text": "我用侦查检定判断黑暗里的处境，再朝黑暗走去",
                "freeform_kind": "off_map_move",
                "requested_skill_key": "spot_hidden",
            }
        },
    )
    outcome = resolution.scene_batches[0].outcomes[0]

    assert outcome.success is False
    assert outcome.requested_skill_key == "spot_hidden"
    assert [roll.visibility for roll in resolution.dice_rolls] == ["public", "public"]
    assert resolution.dice_rolls[0].source == "runtime_freeform_check"
    assert resolution.dice_rolls[0].success_level == "fumble"
    assert resolution.dice_rolls[0].display_text == (
        "spot_hidden CHECK\n投掷骰子 d100=100\n目标值 80：大失败"
    )
    assert resolution.dice_rolls[1].source == "status_consequence"
    assert resolution.dice_rolls[1].display_text == (
        "SAN CHECK\n投掷骰子 1d2=1\nSAN: 50->49"
    )
    assert session.player_states["p1"].investigator.state.sanity == 49
    assert session.player_states["p1"].investigator.state.hit_points == 11


def test_repeated_tokoyami_boundary_freeform_triggers_runtime_checks_and_bad_end() -> None:
    rolls = iter([99, 99, 99, 99, 99])
    runtime = SceneRuntime(roll_provider=lambda: next(rolls, 99))
    session = runtime.create_session(
        "tokoyami_subset",
        ["p1"],
        player_cards=build_player_cards(["p1"]),
    )

    scripted_inputs = [
        {
            "type": "freeform",
            "text": "前往七号车厢",
            "freeform_kind": "off_map_move",
            "intended_target": "七号车厢",
        },
        {
            "type": "freeform",
            "text": "探出半个身子出去尝试看深渊底下有什么",
            "freeform_kind": "off_map_move",
        },
        {
            "type": "freeform",
            "text": "尝试从门框外观察列车后面车厢的情况，试图寻找声音来源",
            "freeform_kind": "off_map_move",
        },
        {
            "type": "freeform",
            "text": "朝着黑暗走去",
            "freeform_kind": "off_map_move",
        },
    ]

    resolutions = [
        _submit_and_resolve(
            runtime,
            session_id=session.session_id,
            intents={"p1": intent},
        )
        for intent in scripted_inputs
    ]

    assert [len(result.dice_rolls) for result in resolutions] == [1, 1, 2, 2]
    assert all(
        roll.source == "status_consequence" and roll.visibility == "keeper"
        for result in resolutions
        for roll in result.dice_rolls
    )

    final_resolution = resolutions[-1]
    final_outcome = final_resolution.scene_batches[0].outcomes[0]
    assert final_outcome.success is False
    assert "运行时推进时钟:rear_threat+2" in final_outcome.effects_applied
    assert final_resolution.applied_clock_deltas["rear_threat"] == 3
    assert final_resolution.clock_values["rear_threat"] == 10
    assert "rear_threat:10" in final_resolution.triggered_clock_events
    assert final_resolution.new_stage == "bad_end"
    assert final_resolution.resolved_ending == "bad_end"
    assert session.story_state.current_stage_id == "bad_end"
    assert session.resolved_ending == "bad_end"
    assert session.player_states["p1"].current_scene_id == "car_6"
    assert session.player_states["p1"].investigator.state.sanity == 38
    assert session.player_states["p1"].investigator.state.hit_points == 9


def test_runtime_freeform_clock_respects_successful_agent_check() -> None:
    planner = _FreeformStealthPlanner()
    runtime = SceneRuntime(roll_provider=lambda: 1, plan_agent=planner)
    session = runtime.create_session(
        "tokoyami_subset",
        ["p1"],
        player_cards=build_player_cards(["p1"]),
    )

    scripted_inputs = [
            {
                "type": "freeform",
                "text": "前往七号车厢",
                "freeform_kind": "off_map_move",
                "intended_target": "七号车厢",
                "requested_skill_key": "stealth",
            },
            {
                "type": "freeform",
                "text": "探出半个身子出去尝试看深渊底下有什么",
                "freeform_kind": "off_map_move",
                "requested_skill_key": "stealth",
            },
            {
                "type": "freeform",
                "text": "尝试从门框外观察列车后面车厢的情况，试图寻找声音来源",
                "freeform_kind": "off_map_move",
                "requested_skill_key": "stealth",
            },
            {
                "type": "freeform",
                "text": "朝着黑暗走去",
                "freeform_kind": "off_map_move",
                "requested_skill_key": "stealth",
            },
            {
                "type": "freeform",
                "text": "继续朝着黑暗走去",
                "freeform_kind": "off_map_move",
                "requested_skill_key": "stealth",
            },
            {
                "type": "freeform",
                "text": "不顾一切大步跑起来",
                "freeform_kind": "generic",
                "requested_skill_key": "stealth",
            },
        ]
    resolutions = [
        _submit_and_resolve(
            runtime,
            session_id=session.session_id,
            intents={"p1": intent},
        )
        for intent in scripted_inputs
    ]

    final_resolution = resolutions[-1]
    assert final_resolution.scene_batches[0].outcomes[0].success is True
    assert final_resolution.applied_clock_deltas["rear_threat"] == 2
    assert final_resolution.clock_values["rear_threat"] == 9
    assert final_resolution.resolved_ending is None
    assert "rear_threat:10" not in final_resolution.triggered_clock_events
    assert all(
        roll.source == "dynamic_agent_check" and roll.visibility == "public"
        for result in resolutions
        for roll in result.dice_rolls
    )
    assert session.player_states["p1"].investigator.state.sanity == 50
    assert session.player_states["p1"].investigator.state.hit_points == 11


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

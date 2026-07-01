from __future__ import annotations

import pytest

from scenario.scene import MovementDecision, SceneLink, SceneMovementRules


def test_movement_decision_defaults_reason_to_empty_string() -> None:
    decision = MovementDecision(allowed=False)

    assert decision.allowed is False
    assert decision.reason == ""
    assert decision.reason_code == ""


def test_scene_movement_rules_entrypoint_is_explicitly_unimplemented() -> None:
    rules = SceneMovementRules()

    with pytest.raises(NotImplementedError):
        rules.evaluate_transition(from_scene_id="car_1", to_scene_id="car_2")


def test_scene_movement_rules_allows_transition_when_flags_are_satisfied() -> None:
    rules = SceneMovementRules(
        scene_links=[
            SceneLink(
                from_scene_id="car_1",
                to_scene_id="car_2",
                required_flags=["key_obtained"],
            )
        ],
        active_flags={"key_obtained"},
    )

    decision = rules.evaluate_transition(from_scene_id="car_1", to_scene_id="car_2")

    assert decision.allowed is True
    assert decision.reason == ""


def test_scene_movement_rules_blocks_transition_when_flag_is_missing() -> None:
    rules = SceneMovementRules(
        scene_links=[
            SceneLink(
                from_scene_id="car_1",
                to_scene_id="car_2",
                required_flags=["key_obtained"],
                block_reason="你还没有拿到钥匙。",
            )
        ],
        active_flags=set(),
    )

    decision = rules.evaluate_transition(from_scene_id="car_1", to_scene_id="car_2")

    assert decision.allowed is False
    assert decision.reason == "你还没有拿到钥匙。"
    assert decision.reason_code == "missing_flags"
    assert decision.missing_flags == ["key_obtained"]


def test_scene_movement_rules_blocks_transition_when_stage_is_missing() -> None:
    rules = SceneMovementRules(
        scene_links=[
            SceneLink(
                from_scene_id="car_2",
                to_scene_id="head_car",
                required_flags=["path_through_clickers"],
                required_stages=["breakthrough"],
                block_reason="你还没有安全穿过循声者所在的车厢。",
            )
        ],
        active_flags={"path_through_clickers"},
        active_stage_id="key_ready",
    )

    decision = rules.evaluate_transition(from_scene_id="car_2", to_scene_id="head_car")

    assert decision.allowed is False
    assert decision.reason == "你还没有安全穿过循声者所在的车厢。"
    assert decision.reason_code == "missing_stage"
    assert decision.missing_stages == ["breakthrough"]


def test_scene_movement_rules_classifies_missing_link_as_no_link() -> None:
    rules = SceneMovementRules(
        scene_links=[SceneLink(from_scene_id="foyer", to_scene_id="storage")],
    )

    decision = rules.evaluate_transition(
        from_scene_id="foyer",
        to_scene_id="exit",
    )

    assert decision.allowed is False
    assert decision.reason_code == "no_link"


def test_list_reachable_scenes_only_returns_allowed_destinations() -> None:
    rules = SceneMovementRules(
        scene_links=[
            SceneLink(from_scene_id="car_1", to_scene_id="car_2"),
            SceneLink(
                from_scene_id="car_1",
                to_scene_id="car_3",
                required_flags=["bridge_lowered"],
            ),
        ],
        active_flags=set(),
    )

    reachable = rules.list_reachable_scenes(from_scene_id="car_1")

    assert reachable == ["car_2"]

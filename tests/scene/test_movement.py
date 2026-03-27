from __future__ import annotations

import pytest

from scene.movement import MovementDecision, SceneMovementRules
from scene.scene import SceneLink


def test_movement_decision_defaults_reason_to_empty_string() -> None:
    decision = MovementDecision(allowed=False)

    assert decision.allowed is False
    assert decision.reason == ""


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

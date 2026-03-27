from __future__ import annotations

import pytest

from scene.movement import MovementDecision, SceneMovementRules


def test_movement_decision_defaults_reason_to_empty_string() -> None:
    decision = MovementDecision(allowed=False)

    assert decision.allowed is False
    assert decision.reason == ""


def test_scene_movement_rules_entrypoint_is_explicitly_unimplemented() -> None:
    rules = SceneMovementRules()

    with pytest.raises(NotImplementedError):
        rules.evaluate_transition(from_scene_id="car_1", to_scene_id="car_2")

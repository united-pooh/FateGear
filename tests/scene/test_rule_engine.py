from __future__ import annotations

from scenario.io import load_module_by_id
from scenario.runtime import RuleEngine, SceneRuntime
from tests.scene.card_fixtures import build_player_cards


def test_rule_engine_rejects_action_outside_current_scene() -> None:
    runtime = SceneRuntime()
    session = runtime.create_session(
        "generic_mvp",
        ["p1"],
        player_cards=build_player_cards(["p1"]),
    )
    module = load_module_by_id("generic_mvp")
    action = module.action_map()["find_key"]
    engine = RuleEngine()

    allowed, reason = engine.can_execute_action(
        action=action,
        session=session,
        player_id="p1",
    )

    assert allowed is False
    assert reason == "动作不在玩家当前场景中"


def test_rule_engine_applies_clock_delta_with_max_cap() -> None:
    runtime = SceneRuntime()
    session = runtime.create_session(
        "generic_mvp",
        ["p1"],
        player_cards=build_player_cards(["p1"]),
    )
    module = load_module_by_id("generic_mvp")
    engine = RuleEngine()

    engine.apply_clock_deltas(
        session,
        module=module,
        deltas={"alarm": 99},
    )

    assert session.clock_values["alarm"] == 3


def test_rule_engine_triggers_clock_threshold_only_once() -> None:
    runtime = SceneRuntime()
    session = runtime.create_session(
        "generic_mvp",
        ["p1"],
        player_cards=build_player_cards(["p1"]),
    )
    module = load_module_by_id("generic_mvp")
    engine = RuleEngine()

    engine.apply_clock_deltas(
        session,
        module=module,
        deltas={"alarm": 1},
    )
    first = engine.trigger_clock_events(session, module)
    second = engine.trigger_clock_events(session, module)

    assert first == ["alarm:1"]
    assert second == []
    assert "alarm_triggered" in session.global_flags

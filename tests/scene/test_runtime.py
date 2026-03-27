from __future__ import annotations

import logging

from scene.runtime import RuntimeEvent, SceneRuntime

LOGGER = logging.getLogger(__name__)


def _submit_and_resolve(
    runtime: SceneRuntime,
    *,
    session_id: str,
    intents: dict[str, dict[str, object]],
):
    for player_id, intent in intents.items():
        runtime.submit_intent(session_id, player_id, intent)
    return runtime.resolve_turn(session_id)


def _find_outcome(resolution, *, player_id: str):
    for batch in resolution.scene_batches:
        for outcome in batch.outcomes:
            if outcome.player_id == player_id:
                return outcome
    raise AssertionError(f"未找到玩家 {player_id} 的结算结果")


def _log_turn_resolution(resolution) -> None:
    for event in resolution.event_log:
        LOGGER.info(event.to_log_line())


def _find_events(
    resolution,
    *,
    event_type: str,
    player_id: str = "",
) -> list[RuntimeEvent]:
    return [
        event
        for event in resolution.event_log
        if event.type == event_type and (not player_id or event.player_id == player_id)
    ]


def test_create_session_initializes_players_scenes_and_clocks() -> None:
    runtime = SceneRuntime()

    session = runtime.create_session("generic_mvp", ["p1", "p2"])

    assert session.module_id == "generic_mvp"
    assert session.current_turn == 1
    assert session.clock_values == {"alarm": 0}
    assert session.player_states["p1"].current_scene_id == "foyer"
    assert set(session.scene_instances) == {"foyer", "storage", "control", "exit"}


def test_turn_only_advances_on_resolve_and_links_unlock_after_flag() -> None:
    runtime = SceneRuntime()
    session = runtime.create_session("generic_mvp", ["p1"])

    assert runtime.list_reachable_scenes(session, "p1") == ["storage"]

    runtime.submit_intent(
        session.session_id,
        "p1",
        {"type": "move", "target_scene_id": "storage"},
    )
    assert session.current_turn == 1

    runtime.resolve_turn(session.session_id)
    assert session.current_turn == 2
    assert session.player_states["p1"].current_scene_id == "storage"

    available_actions = {
        action.id for action in runtime.list_available_actions(session, "p1")
    }
    assert available_actions == {"find_key"}

    _submit_and_resolve(
        runtime,
        session_id=session.session_id,
        intents={"p1": {"type": "action", "action_id": "find_key"}},
    )
    _submit_and_resolve(
        runtime,
        session_id=session.session_id,
        intents={"p1": {"type": "action", "action_id": "unlock_control_door"}},
    )
    _submit_and_resolve(
        runtime,
        session_id=session.session_id,
        intents={"p1": {"type": "move", "target_scene_id": "foyer"}},
    )

    assert "control" in runtime.list_reachable_scenes(session, "p1")


def test_same_turn_scene_batches_use_the_same_snapshot() -> None:
    runtime = SceneRuntime()
    session = runtime.create_session("generic_mvp", ["p1", "p2"])

    _submit_and_resolve(
        runtime,
        session_id=session.session_id,
        intents={"p1": {"type": "move", "target_scene_id": "storage"}},
    )
    _submit_and_resolve(
        runtime,
        session_id=session.session_id,
        intents={"p1": {"type": "action", "action_id": "find_key"}},
    )

    resolution = _submit_and_resolve(
        runtime,
        session_id=session.session_id,
        intents={
            "p1": {"type": "action", "action_id": "unlock_control_door"},
            "p2": {"type": "move", "target_scene_id": "control"},
        },
    )

    p2_outcome = _find_outcome(resolution, player_id="p2")
    assert p2_outcome.success is False
    assert session.player_states["p2"].current_scene_id == "foyer"
    assert "door_unlocked" in session.global_flags

    next_resolution = _submit_and_resolve(
        runtime,
        session_id=session.session_id,
        intents={"p2": {"type": "move", "target_scene_id": "control"}},
    )
    assert _find_outcome(next_resolution, player_id="p2").success is True
    assert session.player_states["p2"].current_scene_id == "control"


def test_action_effects_update_clocks_thresholds_and_once_actions() -> None:
    runtime = SceneRuntime()
    session = runtime.create_session("generic_mvp", ["p1"])

    _submit_and_resolve(
        runtime,
        session_id=session.session_id,
        intents={"p1": {"type": "move", "target_scene_id": "storage"}},
    )
    _submit_and_resolve(
        runtime,
        session_id=session.session_id,
        intents={"p1": {"type": "action", "action_id": "find_key"}},
    )
    _submit_and_resolve(
        runtime,
        session_id=session.session_id,
        intents={"p1": {"type": "action", "action_id": "unlock_control_door"}},
    )
    _submit_and_resolve(
        runtime,
        session_id=session.session_id,
        intents={"p1": {"type": "move", "target_scene_id": "foyer"}},
    )
    _submit_and_resolve(
        runtime,
        session_id=session.session_id,
        intents={"p1": {"type": "move", "target_scene_id": "control"}},
    )

    resolution = _submit_and_resolve(
        runtime,
        session_id=session.session_id,
        intents={"p1": {"type": "action", "action_id": "prime_machine"}},
    )

    assert resolution.event_log
    assert isinstance(resolution.event_log[0], RuntimeEvent)
    assert "prime_machine" in session.completed_actions
    assert session.scene_instances["control"].has_event_occurred is True
    assert resolution.applied_clock_deltas == {"alarm": 1}
    assert session.clock_values["alarm"] == 1
    assert "alarm:1" in resolution.triggered_clock_events
    assert "alarm_triggered" in session.global_flags

    failed_resolution = _submit_and_resolve(
        runtime,
        session_id=session.session_id,
        intents={"p1": {"type": "action", "action_id": "prime_machine"}},
    )
    failed_outcome = _find_outcome(failed_resolution, player_id="p1")
    assert failed_outcome.success is False
    assert failed_outcome.reason == "该动作在本会话中已经执行过"


def test_generic_module_happy_path_reaches_escape_ending() -> None:
    runtime = SceneRuntime()
    session = runtime.create_session("generic_mvp", ["p1"])

    _submit_and_resolve(
        runtime,
        session_id=session.session_id,
        intents={"p1": {"type": "move", "target_scene_id": "storage"}},
    )
    _submit_and_resolve(
        runtime,
        session_id=session.session_id,
        intents={"p1": {"type": "action", "action_id": "find_key"}},
    )
    _submit_and_resolve(
        runtime,
        session_id=session.session_id,
        intents={"p1": {"type": "action", "action_id": "unlock_control_door"}},
    )
    _submit_and_resolve(
        runtime,
        session_id=session.session_id,
        intents={"p1": {"type": "move", "target_scene_id": "foyer"}},
    )
    _submit_and_resolve(
        runtime,
        session_id=session.session_id,
        intents={"p1": {"type": "move", "target_scene_id": "control"}},
    )
    _submit_and_resolve(
        runtime,
        session_id=session.session_id,
        intents={"p1": {"type": "action", "action_id": "prime_machine"}},
    )
    _submit_and_resolve(
        runtime,
        session_id=session.session_id,
        intents={"p1": {"type": "action", "action_id": "open_exit"}},
    )
    resolution = _submit_and_resolve(
        runtime,
        session_id=session.session_id,
        intents={"p1": {"type": "move", "target_scene_id": "exit"}},
    )

    assert resolution.resolved_ending == "safe_escape"
    assert session.resolved_ending == "safe_escape"


def test_tokoyami_subset_happy_path_and_clock_threshold() -> None:
    runtime = SceneRuntime()
    session = runtime.create_session("tokoyami_subset", ["p1"])

    resolution = _submit_and_resolve(
        runtime,
        session_id=session.session_id,
        intents={"p1": {"type": "action", "action_id": "inspect_note"}},
    )
    _log_turn_resolution(resolution)
    resolution = _submit_and_resolve(
        runtime,
        session_id=session.session_id,
        intents={"p1": {"type": "move", "target_scene_id": "car_4"}},
    )
    _log_turn_resolution(resolution)
    resolution = _submit_and_resolve(
        runtime,
        session_id=session.session_id,
        intents={"p1": {"type": "action", "action_id": "revive_attendant"}},
    )
    _log_turn_resolution(resolution)
    resolution = _submit_and_resolve(
        runtime,
        session_id=session.session_id,
        intents={"p1": {"type": "move", "target_scene_id": "car_3"}},
    )
    _log_turn_resolution(resolution)
    resolution = _submit_and_resolve(
        runtime,
        session_id=session.session_id,
        intents={"p1": {"type": "action", "action_id": "find_key"}},
    )
    _log_turn_resolution(resolution)
    resolution = _submit_and_resolve(
        runtime,
        session_id=session.session_id,
        intents={"p1": {"type": "move", "target_scene_id": "car_2"}},
    )
    _log_turn_resolution(resolution)
    resolution = _submit_and_resolve(
        runtime,
        session_id=session.session_id,
        intents={"p1": {"type": "action", "action_id": "sneak_past_clickers"}},
    )
    _log_turn_resolution(resolution)
    resolution = _submit_and_resolve(
        runtime,
        session_id=session.session_id,
        intents={"p1": {"type": "move", "target_scene_id": "head_car"}},
    )
    _log_turn_resolution(resolution)
    resolution = _submit_and_resolve(
        runtime,
        session_id=session.session_id,
        intents={"p1": {"type": "action", "action_id": "accelerate_train"}},
    )
    _log_turn_resolution(resolution)

    assert resolution.resolved_ending == "true_end"
    assert session.resolved_ending == "true_end"
    assert "rear_threat_warning" in session.global_flags
    accelerate_events = _find_events(
        resolution,
        event_type="action_resolved",
        player_id="p1",
    )
    assert any(
        event.action_id == "accelerate_train" and event.success is True
        for event in accelerate_events
    )

    threat_runtime = SceneRuntime()
    threat_session = threat_runtime.create_session("tokoyami_subset", ["p1"])
    last_resolution = None
    for _ in range(10):
        last_resolution = threat_runtime.resolve_turn(threat_session.session_id)
        assert last_resolution is not None
        _log_turn_resolution(last_resolution)

    assert last_resolution is not None
    assert "rear_threat:10" in last_resolution.triggered_clock_events
    assert "rear_threat_overwhelms" in threat_session.global_flags
    assert any(
        event.type == "clock_events_triggered"
        and "rear_threat:10" in event.triggered_clock_events
        for event in last_resolution.event_log
    )


def test_tokoyami_subset_multiplayer_shared_progression_and_logs() -> None:
    runtime = SceneRuntime()
    session = runtime.create_session("tokoyami_subset", ["p1", "p2"])

    resolution = _submit_and_resolve(
        runtime,
        session_id=session.session_id,
        intents={
            "p1": {"type": "action", "action_id": "inspect_note"},
            "p2": {"type": "move", "target_scene_id": "car_4"},
        },
    )
    _log_turn_resolution(resolution)

    resolution = _submit_and_resolve(
        runtime,
        session_id=session.session_id,
        intents={
            "p1": {"type": "move", "target_scene_id": "car_4"},
            "p2": {"type": "action", "action_id": "revive_attendant"},
        },
    )
    _log_turn_resolution(resolution)

    resolution = _submit_and_resolve(
        runtime,
        session_id=session.session_id,
        intents={
            "p1": {"type": "move", "target_scene_id": "car_3"},
            "p2": {"type": "move", "target_scene_id": "car_3"},
        },
    )
    _log_turn_resolution(resolution)

    resolution = _submit_and_resolve(
        runtime,
        session_id=session.session_id,
        intents={
            "p1": {"type": "action", "action_id": "find_key"},
            "p2": {"type": "move", "target_scene_id": "car_2"},
        },
    )
    _log_turn_resolution(resolution)

    resolution = _submit_and_resolve(
        runtime,
        session_id=session.session_id,
        intents={
            "p1": {"type": "move", "target_scene_id": "car_2"},
            "p2": {"type": "move", "target_scene_id": "head_car"},
        },
    )
    _log_turn_resolution(resolution)
    failed_move = _find_outcome(resolution, player_id="p2")
    assert failed_move.success is False
    assert "path_through_clickers" not in session.global_flags

    resolution = _submit_and_resolve(
        runtime,
        session_id=session.session_id,
        intents={
            "p1": {"type": "action", "action_id": "sneak_past_clickers"},
            "p2": {"type": "move", "target_scene_id": "head_car"},
        },
    )
    _log_turn_resolution(resolution)
    blocked_move = _find_outcome(resolution, player_id="p2")
    assert blocked_move.success is False
    assert "path_through_clickers" in session.global_flags
    assert any(
        event.type == "movement_attempted"
        and event.player_id == "p2"
        and event.to_scene_id == "head_car"
        and event.success is False
        for event in resolution.event_log
    )

    resolution = _submit_and_resolve(
        runtime,
        session_id=session.session_id,
        intents={"p2": {"type": "move", "target_scene_id": "head_car"}},
    )
    _log_turn_resolution(resolution)
    assert _find_outcome(resolution, player_id="p2").success is True

    resolution = _submit_and_resolve(
        runtime,
        session_id=session.session_id,
        intents={"p2": {"type": "action", "action_id": "accelerate_train"}},
    )
    _log_turn_resolution(resolution)

    assert resolution.resolved_ending == "true_end"
    assert session.resolved_ending == "true_end"
    assert any(
        event.type == "ending_reached" and event.ending_id == "true_end"
        for event in resolution.event_log
    )

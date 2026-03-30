from __future__ import annotations

from pathlib import Path

import pytest

from scenario.runtime import RuntimeEvent, SceneRuntime, TurnResolution

SCENE_LOG_DIR = Path(__file__).resolve().parents[2] / "log" / "scene"
STORY_LOG_DIR = Path(__file__).resolve().parents[2] / "log" / "story"
STORY_EVENT_TYPES = {
    "turn_started",
    "action_resolved",
    "movement_committed",
    "flags_changed",
    "clocks_advanced",
    "clock_events_triggered",
    "story_transition_applied",
    "ending_reached",
    "turn_completed",
}


def _submit_and_resolve(
    runtime: SceneRuntime,
    *,
    session_id: str,
    intents: dict[str, dict[str, object]],
    history: list[TurnResolution] | None = None,
) -> TurnResolution:
    for player_id, intent in intents.items():
        runtime.submit_intent(session_id, player_id, intent)
    resolution = runtime.resolve_turn(session_id)
    if history is not None:
        history.append(resolution)
    return resolution


def _resolve_turn(
    runtime: SceneRuntime,
    *,
    session_id: str,
    history: list[TurnResolution] | None = None,
) -> TurnResolution:
    resolution = runtime.resolve_turn(session_id)
    if history is not None:
        history.append(resolution)
    return resolution


def _find_outcome(resolution: TurnResolution, *, player_id: str):
    for batch in resolution.scene_batches:
        for outcome in batch.outcomes:
            if outcome.player_id == player_id:
                return outcome
    raise AssertionError(f"未找到玩家 {player_id} 的结算结果")


def _find_events(
    resolution: TurnResolution,
    *,
    event_type: str,
    player_id: str = "",
) -> list[RuntimeEvent]:
    return [
        event
        for event in resolution.event_log
        if event.type == event_type and (not player_id or event.player_id == player_id)
    ]


def _format_story_signal(signal) -> str:
    if signal.type == "scene_entered":
        return (
            f"scene_entered player={signal.player_id} "
            f"scene={signal.scene_id} turn={signal.turn_no}"
        )
    if signal.type == "action_succeeded":
        return (
            f"action_succeeded player={signal.player_id} "
            f"action={signal.action_id} scene={signal.scene_id} turn={signal.turn_no}"
        )
    return (
        f"clock_threshold_triggered clock={signal.clock_id} "
        f"threshold={signal.threshold} turn={signal.turn_no}"
    )


def _write_runtime_logs(
    name: str,
    *,
    session,
    resolutions: list[TurnResolution],
) -> None:
    SCENE_LOG_DIR.mkdir(parents=True, exist_ok=True)
    STORY_LOG_DIR.mkdir(parents=True, exist_ok=True)

    scene_lines = [
        f"scenario={name}",
        f"module_id={session.module_id}",
        f"session_id={session.session_id}",
        "",
    ]
    story_lines = [
        f"scenario={name}",
        f"module_id={session.module_id}",
        f"session_id={session.session_id}",
        f"final_stage={session.story_state.current_stage_id}",
        f"resolved_ending={session.resolved_ending or ''}",
        "",
    ]

    for resolution in resolutions:
        scene_lines.append(
            f"=== turn {resolution.turn_no} -> {resolution.next_turn} ==="
        )
        scene_lines.extend(event.to_log_line() for event in resolution.event_log)
        scene_lines.append("")

        story_lines.append(
            f"=== turn {resolution.turn_no} -> {resolution.next_turn} ==="
        )
        if resolution.story_signals:
            story_lines.extend(
                _format_story_signal(signal) for signal in resolution.story_signals
            )
        else:
            story_lines.append("no_story_signal")
        if resolution.applied_story_transition_id is not None:
            story_lines.append(
                f"transition={resolution.applied_story_transition_id} new_stage={resolution.new_stage}"
            )
        else:
            story_lines.append("transition=<none>")
        if resolution.resolved_ending is not None:
            story_lines.append(
                f"resolved_ending={resolution.resolved_ending} ending_result={resolution.ending_result}"
            )
        story_lines.extend(
            event.to_log_line()
            for event in resolution.event_log
            if event.type in STORY_EVENT_TYPES
        )
        story_lines.append("")

    (SCENE_LOG_DIR / f"{name}.log").write_text(
        "\n".join(scene_lines),
        encoding="utf-8",
    )
    (STORY_LOG_DIR / f"{name}.log").write_text(
        "\n".join(story_lines),
        encoding="utf-8",
    )


def test_create_session_initializes_players_scenes_clocks_and_story_stage() -> None:
    runtime = SceneRuntime()

    session = runtime.create_session("generic_mvp", ["p1", "p2"])

    assert session.module_id == "generic_mvp"
    assert session.current_turn == 1
    assert session.story_state.current_stage_id == "setup"
    assert session.clock_values == {"alarm": 0}
    assert session.player_states["p1"].current_scene_id == "foyer"
    assert set(session.scene_instances) == {"foyer", "storage", "control", "exit"}


def test_add_player_joins_waiting_session_at_entry_scene() -> None:
    runtime = SceneRuntime()
    session = runtime.create_session("generic_mvp", ["kp"])

    player_state = runtime.add_player(session.session_id, "p2")

    assert player_state.player_id == "p2"
    assert player_state.current_scene_id == "foyer"
    assert player_state.last_scene_id == "foyer"
    assert set(session.player_states) == {"kp", "p2"}


def test_add_player_rejects_join_after_session_has_started() -> None:
    runtime = SceneRuntime()
    session = runtime.create_session("generic_mvp", ["kp"])

    runtime.resolve_turn(session.session_id)

    with pytest.raises(ValueError, match="已经开始"):
        runtime.add_player(session.session_id, "late_player")


def test_turn_only_advances_on_resolve_and_links_unlock_after_story_transition() -> (
    None
):
    runtime = SceneRuntime()
    session = runtime.create_session("generic_mvp", ["p1"])
    resolutions: list[TurnResolution] = []

    assert runtime.list_reachable_scenes(session, "p1") == ["storage"]

    runtime.submit_intent(
        session.session_id,
        "p1",
        {"type": "move", "target_scene_id": "storage"},
    )
    assert session.current_turn == 1

    first_resolution = _resolve_turn(
        runtime,
        session_id=session.session_id,
        history=resolutions,
    )
    assert first_resolution.new_stage is None
    assert session.current_turn == 2
    assert session.story_state.current_stage_id == "setup"
    assert session.player_states["p1"].current_scene_id == "storage"

    available_actions = {
        action.id for action in runtime.list_available_actions(session, "p1")
    }
    assert available_actions == {"find_key"}

    find_key_resolution = _submit_and_resolve(
        runtime,
        session_id=session.session_id,
        intents={"p1": {"type": "action", "action_id": "find_key"}},
        history=resolutions,
    )
    assert find_key_resolution.applied_story_transition_id is None
    assert session.story_state.current_stage_id == "setup"

    unlock_resolution = _submit_and_resolve(
        runtime,
        session_id=session.session_id,
        intents={"p1": {"type": "action", "action_id": "unlock_control_door"}},
        history=resolutions,
    )
    assert unlock_resolution.applied_story_transition_id == "unlock_access"
    assert unlock_resolution.new_stage == "access_opened"
    assert session.story_state.current_stage_id == "access_opened"

    _submit_and_resolve(
        runtime,
        session_id=session.session_id,
        intents={"p1": {"type": "move", "target_scene_id": "foyer"}},
        history=resolutions,
    )

    assert "control" in runtime.list_reachable_scenes(session, "p1")
    _write_runtime_logs(
        "turn_advancement_and_link_unlocks",
        session=session,
        resolutions=resolutions,
    )


def test_same_turn_scene_batches_use_the_same_snapshot() -> None:
    runtime = SceneRuntime()
    session = runtime.create_session("generic_mvp", ["p1", "p2"])
    resolutions: list[TurnResolution] = []

    _submit_and_resolve(
        runtime,
        session_id=session.session_id,
        intents={"p1": {"type": "move", "target_scene_id": "storage"}},
        history=resolutions,
    )
    _submit_and_resolve(
        runtime,
        session_id=session.session_id,
        intents={"p1": {"type": "action", "action_id": "find_key"}},
        history=resolutions,
    )

    resolution = _submit_and_resolve(
        runtime,
        session_id=session.session_id,
        intents={
            "p1": {"type": "action", "action_id": "unlock_control_door"},
            "p2": {"type": "move", "target_scene_id": "control"},
        },
        history=resolutions,
    )

    p2_outcome = _find_outcome(resolution, player_id="p2")
    assert p2_outcome.success is False
    assert session.player_states["p2"].current_scene_id == "foyer"
    assert "door_unlocked" in session.global_flags
    assert session.story_state.current_stage_id == "access_opened"

    next_resolution = _submit_and_resolve(
        runtime,
        session_id=session.session_id,
        intents={"p2": {"type": "move", "target_scene_id": "control"}},
        history=resolutions,
    )
    assert _find_outcome(next_resolution, player_id="p2").success is True
    assert session.player_states["p2"].current_scene_id == "control"
    _write_runtime_logs(
        "same_turn_scene_batches_snapshot",
        session=session,
        resolutions=resolutions,
    )


def test_action_effects_update_clocks_thresholds_story_stage_and_once_actions() -> None:
    runtime = SceneRuntime()
    session = runtime.create_session("generic_mvp", ["p1"])
    resolutions: list[TurnResolution] = []

    _submit_and_resolve(
        runtime,
        session_id=session.session_id,
        intents={"p1": {"type": "move", "target_scene_id": "storage"}},
        history=resolutions,
    )
    _submit_and_resolve(
        runtime,
        session_id=session.session_id,
        intents={"p1": {"type": "action", "action_id": "find_key"}},
        history=resolutions,
    )
    _submit_and_resolve(
        runtime,
        session_id=session.session_id,
        intents={"p1": {"type": "action", "action_id": "unlock_control_door"}},
        history=resolutions,
    )
    _submit_and_resolve(
        runtime,
        session_id=session.session_id,
        intents={"p1": {"type": "move", "target_scene_id": "foyer"}},
        history=resolutions,
    )
    _submit_and_resolve(
        runtime,
        session_id=session.session_id,
        intents={"p1": {"type": "move", "target_scene_id": "control"}},
        history=resolutions,
    )

    resolution = _submit_and_resolve(
        runtime,
        session_id=session.session_id,
        intents={"p1": {"type": "action", "action_id": "prime_machine"}},
        history=resolutions,
    )

    assert resolution.event_log
    assert isinstance(resolution.event_log[0], RuntimeEvent)
    assert resolution.applied_story_transition_id == "prime_system"
    assert resolution.new_stage == "system_primed"
    assert "prime_machine" in session.completed_actions
    assert session.story_state.current_stage_id == "system_primed"
    assert session.scene_instances["control"].has_event_occurred is True
    assert resolution.applied_clock_deltas == {"alarm": 1}
    assert session.clock_values["alarm"] == 1
    assert "alarm:1" in resolution.triggered_clock_events
    assert "alarm_triggered" in session.global_flags

    failed_resolution = _submit_and_resolve(
        runtime,
        session_id=session.session_id,
        intents={"p1": {"type": "action", "action_id": "prime_machine"}},
        history=resolutions,
    )
    failed_outcome = _find_outcome(failed_resolution, player_id="p1")
    assert failed_outcome.success is False
    assert failed_outcome.reason == "当前剧情阶段不允许执行该动作"
    _write_runtime_logs(
        "action_effects_and_story_stage",
        session=session,
        resolutions=resolutions,
    )


def test_generic_module_happy_path_reaches_escape_story_ending() -> None:
    runtime = SceneRuntime()
    session = runtime.create_session("generic_mvp", ["p1"])
    resolutions: list[TurnResolution] = []

    _submit_and_resolve(
        runtime,
        session_id=session.session_id,
        intents={"p1": {"type": "move", "target_scene_id": "storage"}},
        history=resolutions,
    )
    _submit_and_resolve(
        runtime,
        session_id=session.session_id,
        intents={"p1": {"type": "action", "action_id": "find_key"}},
        history=resolutions,
    )
    _submit_and_resolve(
        runtime,
        session_id=session.session_id,
        intents={"p1": {"type": "action", "action_id": "unlock_control_door"}},
        history=resolutions,
    )
    _submit_and_resolve(
        runtime,
        session_id=session.session_id,
        intents={"p1": {"type": "move", "target_scene_id": "foyer"}},
        history=resolutions,
    )
    _submit_and_resolve(
        runtime,
        session_id=session.session_id,
        intents={"p1": {"type": "move", "target_scene_id": "control"}},
        history=resolutions,
    )
    _submit_and_resolve(
        runtime,
        session_id=session.session_id,
        intents={"p1": {"type": "action", "action_id": "prime_machine"}},
        history=resolutions,
    )
    _submit_and_resolve(
        runtime,
        session_id=session.session_id,
        intents={"p1": {"type": "action", "action_id": "open_exit"}},
        history=resolutions,
    )
    resolution = _submit_and_resolve(
        runtime,
        session_id=session.session_id,
        intents={"p1": {"type": "move", "target_scene_id": "exit"}},
        history=resolutions,
    )

    assert resolution.applied_story_transition_id == "escape_facility"
    assert resolution.new_stage == "escaped"
    assert resolution.resolved_ending == "escaped"
    assert session.story_state.current_stage_id == "escaped"
    assert session.story_state.resolved_ending_id == "escaped"
    assert session.resolved_ending == "escaped"
    assert any(
        event.type == "ending_reached" and event.ending_id == "escaped"
        for event in resolution.event_log
    )
    _write_runtime_logs(
        "generic_mvp_escape_story_ending",
        session=session,
        resolutions=resolutions,
    )


def test_tokoyami_subset_happy_path_advances_story_stage() -> None:
    runtime = SceneRuntime()
    session = runtime.create_session("tokoyami_subset", ["p1"])
    resolutions: list[TurnResolution] = []

    resolution = _submit_and_resolve(
        runtime,
        session_id=session.session_id,
        intents={"p1": {"type": "action", "action_id": "inspect_note"}},
        history=resolutions,
    )
    assert resolution.applied_story_transition_id == "awaken_to_informed"
    assert resolution.new_stage == "informed"
    assert session.story_state.current_stage_id == "informed"

    _submit_and_resolve(
        runtime,
        session_id=session.session_id,
        intents={"p1": {"type": "move", "target_scene_id": "car_4"}},
        history=resolutions,
    )
    _submit_and_resolve(
        runtime,
        session_id=session.session_id,
        intents={"p1": {"type": "action", "action_id": "revive_attendant"}},
        history=resolutions,
    )
    _submit_and_resolve(
        runtime,
        session_id=session.session_id,
        intents={"p1": {"type": "move", "target_scene_id": "car_3"}},
        history=resolutions,
    )
    resolution = _submit_and_resolve(
        runtime,
        session_id=session.session_id,
        intents={"p1": {"type": "action", "action_id": "find_key"}},
        history=resolutions,
    )
    assert resolution.applied_story_transition_id == "informed_to_key_ready"
    assert resolution.new_stage == "key_ready"
    assert session.story_state.current_stage_id == "key_ready"

    _submit_and_resolve(
        runtime,
        session_id=session.session_id,
        intents={"p1": {"type": "move", "target_scene_id": "car_2"}},
        history=resolutions,
    )
    resolution = _submit_and_resolve(
        runtime,
        session_id=session.session_id,
        intents={"p1": {"type": "action", "action_id": "sneak_past_clickers"}},
        history=resolutions,
    )
    assert resolution.applied_story_transition_id == "key_ready_to_breakthrough"
    assert resolution.new_stage == "breakthrough"
    assert session.story_state.current_stage_id == "breakthrough"

    _submit_and_resolve(
        runtime,
        session_id=session.session_id,
        intents={"p1": {"type": "move", "target_scene_id": "head_car"}},
        history=resolutions,
    )
    resolution = _submit_and_resolve(
        runtime,
        session_id=session.session_id,
        intents={"p1": {"type": "action", "action_id": "accelerate_train"}},
        history=resolutions,
    )

    assert resolution.applied_story_transition_id == "breakthrough_to_true_end"
    assert resolution.new_stage == "true_end"
    assert resolution.resolved_ending == "true_end"
    assert session.story_state.current_stage_id == "true_end"
    assert session.story_state.resolved_ending_id == "true_end"
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
    _write_runtime_logs(
        "tokoyami_happy_path_story_progression",
        session=session,
        resolutions=resolutions,
    )


def test_tokoyami_subset_clock_threshold_reaches_bad_end_after_informed_stage() -> None:
    runtime = SceneRuntime()
    session = runtime.create_session("tokoyami_subset", ["p1"])
    resolutions: list[TurnResolution] = []

    first_resolution = _submit_and_resolve(
        runtime,
        session_id=session.session_id,
        intents={"p1": {"type": "action", "action_id": "inspect_note"}},
        history=resolutions,
    )
    assert first_resolution.applied_story_transition_id == "awaken_to_informed"
    assert session.story_state.current_stage_id == "informed"

    last_resolution = first_resolution
    for _ in range(9):
        last_resolution = _resolve_turn(
            runtime,
            session_id=session.session_id,
            history=resolutions,
        )

    assert "rear_threat:10" in last_resolution.triggered_clock_events
    assert last_resolution.applied_story_transition_id == "informed_overwhelmed"
    assert last_resolution.new_stage == "bad_end"
    assert last_resolution.resolved_ending == "bad_end"
    assert "rear_threat_overwhelms" in session.global_flags
    assert session.story_state.current_stage_id == "bad_end"
    assert session.story_state.resolved_ending_id == "bad_end"
    assert session.resolved_ending == "bad_end"
    assert any(
        event.type == "ending_reached" and event.ending_id == "bad_end"
        for event in last_resolution.event_log
    )
    _write_runtime_logs(
        "tokoyami_clock_threshold_bad_end",
        session=session,
        resolutions=resolutions,
    )


def test_tokoyami_subset_multiplayer_shared_progression_and_logs() -> None:
    runtime = SceneRuntime()
    session = runtime.create_session("tokoyami_subset", ["p1", "p2"])
    resolutions: list[TurnResolution] = []

    resolution = _submit_and_resolve(
        runtime,
        session_id=session.session_id,
        intents={
            "p1": {"type": "action", "action_id": "inspect_note"},
            "p2": {"type": "move", "target_scene_id": "car_4"},
        },
        history=resolutions,
    )
    assert resolution.applied_story_transition_id == "awaken_to_informed"
    assert session.story_state.current_stage_id == "informed"

    _submit_and_resolve(
        runtime,
        session_id=session.session_id,
        intents={
            "p1": {"type": "move", "target_scene_id": "car_4"},
            "p2": {"type": "action", "action_id": "revive_attendant"},
        },
        history=resolutions,
    )

    _submit_and_resolve(
        runtime,
        session_id=session.session_id,
        intents={
            "p1": {"type": "move", "target_scene_id": "car_3"},
            "p2": {"type": "move", "target_scene_id": "car_3"},
        },
        history=resolutions,
    )

    resolution = _submit_and_resolve(
        runtime,
        session_id=session.session_id,
        intents={
            "p1": {"type": "action", "action_id": "find_key"},
            "p2": {"type": "move", "target_scene_id": "car_2"},
        },
        history=resolutions,
    )
    assert resolution.applied_story_transition_id == "informed_to_key_ready"
    assert session.story_state.current_stage_id == "key_ready"

    resolution = _submit_and_resolve(
        runtime,
        session_id=session.session_id,
        intents={
            "p1": {"type": "move", "target_scene_id": "car_2"},
            "p2": {"type": "move", "target_scene_id": "head_car"},
        },
        history=resolutions,
    )
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
        history=resolutions,
    )
    blocked_move = _find_outcome(resolution, player_id="p2")
    assert blocked_move.success is False
    assert resolution.applied_story_transition_id == "key_ready_to_breakthrough"
    assert session.story_state.current_stage_id == "breakthrough"
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
        history=resolutions,
    )
    assert _find_outcome(resolution, player_id="p2").success is True

    resolution = _submit_and_resolve(
        runtime,
        session_id=session.session_id,
        intents={"p2": {"type": "action", "action_id": "accelerate_train"}},
        history=resolutions,
    )

    assert resolution.applied_story_transition_id == "breakthrough_to_true_end"
    assert resolution.resolved_ending == "true_end"
    assert session.story_state.current_stage_id == "true_end"
    assert session.resolved_ending == "true_end"
    assert any(
        event.type == "ending_reached" and event.ending_id == "true_end"
        for event in resolution.event_log
    )
    _write_runtime_logs(
        "tokoyami_multiplayer_story_progression",
        session=session,
        resolutions=resolutions,
    )

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from scenario.npc_patches import NPCStatePatchProposal
from scenario.runtime import RuntimeEvent, SceneRuntime, TurnResolution

from tests.scene.card_fixtures import build_player_cards, build_test_card

# CoC 7e 人类八维特征默认键
_COC_DEFAULT_KEYS = {"STR", "CON", "SIZ", "DEX", "APP", "INT", "POW", "EDU"}

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


def _runtime_with_deterministic_success() -> SceneRuntime:
    return SceneRuntime(roll_provider=lambda: 1)


def _submit_and_resolve(
    runtime: SceneRuntime,
    *,
    session_id: str,
    intents: dict[str, dict[str, object]],
    history: list[TurnResolution] | None = None,
) -> TurnResolution:
    for player_id, intent in intents.items():
        runtime.submit_intent(session_id, player_id, intent)
    resolution = asyncio.run(runtime.resolve_turn(session_id))
    if history is not None:
        history.append(resolution)
    return resolution


def _resolve_turn(
    runtime: SceneRuntime,
    *,
    session_id: str,
    history: list[TurnResolution] | None = None,
) -> TurnResolution:
    resolution = asyncio.run(runtime.resolve_turn(session_id))
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
    runtime = _runtime_with_deterministic_success()

    session = runtime.create_session(
        "generic_mvp",
        ["p1", "p2"],
        player_cards=build_player_cards(["p1", "p2"]),
    )

    assert session.module_id == "generic_mvp"
    assert session.current_turn == 1
    assert session.story_state.current_stage_id == "setup"
    assert session.clock_values == {"alarm": 0}
    assert session.player_states["p1"].current_scene_id == "foyer"
    assert set(session.scene_instances) == {"foyer", "storage", "control", "exit"}


def test_resolve_turn_replays_expected_turn_without_double_commit() -> None:
    runtime = _runtime_with_deterministic_success()
    session = runtime.create_session(
        "generic_mvp",
        ["p1"],
        player_cards=build_player_cards(["p1"]),
    )
    runtime.submit_intent(
        session.session_id,
        "p1",
        {"type": "move", "target_scene_id": "storage"},
    )

    first = asyncio.run(runtime.resolve_turn(session.session_id, expected_turn=1))
    replay = asyncio.run(runtime.resolve_turn(session.session_id, expected_turn=1))

    assert first.turn_no == 1
    assert replay.turn_no == 1
    assert session.current_turn == 2
    assert session.player_states["p1"].current_scene_id == "storage"
    assert runtime.list_resolved_turns(session.session_id) == [1]
    assert (
        runtime.get_turn_resolution(session.session_id, 1).model_dump()
        == first.model_dump()
    )


def test_resolve_turn_rejects_future_expected_turn() -> None:
    runtime = _runtime_with_deterministic_success()
    session = runtime.create_session(
        "generic_mvp",
        ["p1"],
        player_cards=build_player_cards(["p1"]),
    )

    with pytest.raises(ValueError, match="不能提前结算"):
        asyncio.run(runtime.resolve_turn(session.session_id, expected_turn=2))


def test_concurrent_resolve_with_same_expected_turn_is_idempotent() -> None:
    async def run() -> tuple[TurnResolution, TurnResolution, int]:
        runtime = _runtime_with_deterministic_success()
        session = runtime.create_session(
            "generic_mvp",
            ["p1"],
            player_cards=build_player_cards(["p1"]),
        )
        runtime.submit_intent(
            session.session_id,
            "p1",
            {"type": "move", "target_scene_id": "storage"},
        )
        first, second = await asyncio.gather(
            runtime.resolve_turn(session.session_id, expected_turn=1),
            runtime.resolve_turn(session.session_id, expected_turn=1),
        )
        return first, second, session.current_turn

    first, second, current_turn = asyncio.run(run())

    assert first.turn_no == second.turn_no == 1
    assert first.model_dump() == second.model_dump()
    assert current_turn == 2


def test_add_player_joins_waiting_session_at_entry_scene() -> None:
    runtime = _runtime_with_deterministic_success()
    session = runtime.create_session(
        "generic_mvp",
        ["kp"],
        player_cards=build_player_cards(["kp"]),
    )

    player_state = runtime.add_player(
        session.session_id,
        "p2",
        investigator=build_test_card("p2"),
    )

    assert player_state.player_id == "p2"
    assert player_state.current_scene_id == "foyer"
    assert player_state.last_scene_id == "foyer"
    assert set(session.player_states) == {"kp", "p2"}


def test_add_player_rejects_join_after_session_has_started() -> None:
    runtime = _runtime_with_deterministic_success()
    session = runtime.create_session(
        "generic_mvp",
        ["kp"],
        player_cards=build_player_cards(["kp"]),
    )

    asyncio.run(runtime.resolve_turn(session.session_id))

    with pytest.raises(ValueError, match="已经开始"):
        runtime.add_player(
            session.session_id,
            "late_player",
            investigator=build_test_card("late_player"),
        )


def test_turn_only_advances_on_resolve_and_links_unlock_after_story_transition() -> (
    None
):
    runtime = _runtime_with_deterministic_success()
    session = runtime.create_session(
        "generic_mvp",
        ["p1"],
        player_cards=build_player_cards(["p1"]),
    )
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
    runtime = _runtime_with_deterministic_success()
    session = runtime.create_session(
        "generic_mvp",
        ["p1", "p2"],
        player_cards=build_player_cards(["p1", "p2"]),
    )
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


def test_consecutive_off_map_moves_escalate_to_heavy_penalty() -> None:
    runtime = _runtime_with_deterministic_success()
    session = runtime.create_session(
        "generic_mvp",
        ["p1"],
        player_cards=build_player_cards(["p1"]),
    )

    first_resolution = _submit_and_resolve(
        runtime,
        session_id=session.session_id,
        intents={"p1": {"type": "move", "target_scene_id": "exit"}},
    )
    first_outcome = _find_outcome(first_resolution, player_id="p1")
    assert first_outcome.success is False
    assert first_outcome.reason_code == "no_link"
    assert first_outcome.violation_kind == "off_map_move"
    assert first_outcome.penalty_tier == "warning"
    assert first_outcome.illegal_value == 3
    assert session.player_states["p1"].current_scene_id == "foyer"

    second_resolution = _submit_and_resolve(
        runtime,
        session_id=session.session_id,
        intents={"p1": {"type": "move", "target_scene_id": "exit"}},
    )

    second_outcome = _find_outcome(second_resolution, player_id="p1")
    assert second_outcome.success is False
    assert second_outcome.violation_kind == "off_map_move"
    assert second_outcome.penalty_tier in {"major_penalty", "severe_penalty"}
    assert second_outcome.illegal_value is not None
    assert second_outcome.illegal_value >= 7
    assert session.player_states["p1"].current_scene_id == "foyer"

    risk = session.player_states["p1"].illegal_move_risk
    assert risk.total_count == 2
    assert risk.consecutive_count == 2
    assert risk.last_violation_turn == second_resolution.turn_no
    assert risk.last_penalty_tier in {"major_penalty", "severe_penalty"}

    risk_events = _find_events(
        second_resolution,
        event_type="movement_risk_updated",
        player_id="p1",
    )
    assert len(risk_events) == 1
    assert risk_events[0].violation_kind == "off_map_move"
    assert risk_events[0].reason_code == "no_link"
    assert risk_events[0].score_before == 3
    assert risk_events[0].score_after == second_outcome.illegal_value
    assert risk_events[0].threshold_crossed in {"major_penalty", "severe_penalty"}
    assert risk_events[0].required_threshold == 7

    penalty_events = _find_events(
        second_resolution,
        event_type="movement_penalty_triggered",
        player_id="p1",
    )
    assert len(penalty_events) == 1
    assert penalty_events[0].penalty_tier in {"major_penalty", "severe_penalty"}
    assert penalty_events[0].actual_score == second_outcome.illegal_value
    assert penalty_events[0].effects_applied


def test_intermittent_off_map_moves_eventually_escalate_despite_safe_turns() -> None:
    runtime = _runtime_with_deterministic_success()
    session = runtime.create_session(
        "generic_mvp",
        ["p1"],
        player_cards=build_player_cards(["p1"]),
    )

    _submit_and_resolve(
        runtime,
        session_id=session.session_id,
        intents={"p1": {"type": "move", "target_scene_id": "exit"}},
    )
    legal_resolution = _submit_and_resolve(
        runtime,
        session_id=session.session_id,
        intents={"p1": {"type": "move", "target_scene_id": "storage"}},
    )
    legal_decay_events = _find_events(
        legal_resolution,
        event_type="movement_risk_updated",
        player_id="p1",
    )
    assert legal_decay_events[0].reason_code == "risk_decay"
    assert legal_decay_events[0].decay_applied == 1
    assert session.player_states["p1"].current_scene_id == "storage"

    _submit_and_resolve(
        runtime,
        session_id=session.session_id,
        intents={"p1": {"type": "move", "target_scene_id": "exit"}},
    )
    empty_resolution = _resolve_turn(runtime, session_id=session.session_id)
    empty_decay_events = _find_events(
        empty_resolution,
        event_type="movement_risk_updated",
        player_id="p1",
    )
    assert len(empty_decay_events) == 1
    assert empty_decay_events[0].reason_code == "risk_decay"
    assert empty_decay_events[0].score_after < empty_decay_events[0].score_before

    final_resolution = _submit_and_resolve(
        runtime,
        session_id=session.session_id,
        intents={"p1": {"type": "move", "target_scene_id": "exit"}},
    )

    final_outcome = _find_outcome(final_resolution, player_id="p1")
    assert final_outcome.success is False
    assert final_outcome.violation_kind == "off_map_move"
    assert final_outcome.penalty_tier in {"major_penalty", "severe_penalty"}

    risk = session.player_states["p1"].illegal_move_risk
    assert risk.total_count == 3
    assert risk.last_violation_turn == final_resolution.turn_no
    assert risk.last_penalty_tier in {"major_penalty", "severe_penalty"}

    penalty_events = _find_events(
        final_resolution,
        event_type="movement_penalty_triggered",
        player_id="p1",
    )
    assert len(penalty_events) == 1
    assert penalty_events[0].violation_kind == "off_map_move"
    assert penalty_events[0].actual_score == final_outcome.illegal_value


@pytest.mark.parametrize(
    ("starting_scene_id", "flags", "target_scene_id", "expected_reason_code"),
    [
        ("foyer", set(), "control", "missing_flags"),
        ("control", {"exit_open"}, "exit", "missing_stage"),
    ],
)
def test_blocked_moves_due_to_requirements_do_not_count_as_off_map_move(
    starting_scene_id: str,
    flags: set[str],
    target_scene_id: str,
    expected_reason_code: str,
) -> None:
    runtime = _runtime_with_deterministic_success()
    session = runtime.create_session(
        "generic_mvp",
        ["p1"],
        player_cards=build_player_cards(["p1"]),
    )
    session.player_states["p1"].current_scene_id = starting_scene_id
    session.player_states["p1"].last_scene_id = starting_scene_id
    session.global_flags.update(flags)

    resolution = _submit_and_resolve(
        runtime,
        session_id=session.session_id,
        intents={"p1": {"type": "move", "target_scene_id": target_scene_id}},
    )

    outcome = _find_outcome(resolution, player_id="p1")
    assert outcome.success is False
    assert outcome.reason_code == expected_reason_code
    assert outcome.violation_kind == ""
    assert outcome.penalty_tier == ""
    assert outcome.illegal_value is None

    risk = session.player_states["p1"].illegal_move_risk
    assert risk.illegal_value == 0
    assert risk.total_count == 0
    assert risk.last_violation_turn is None

    attempted_events = _find_events(
        resolution,
        event_type="movement_attempted",
        player_id="p1",
    )
    assert attempted_events[0].reason_code == expected_reason_code
    assert attempted_events[0].violation_kind == ""
    assert not _find_events(
        resolution,
        event_type="movement_risk_updated",
        player_id="p1",
    )
    assert not _find_events(
        resolution,
        event_type="movement_penalty_triggered",
        player_id="p1",
    )


def test_action_effects_update_clocks_thresholds_story_stage_and_once_actions() -> None:
    runtime = _runtime_with_deterministic_success()
    session = runtime.create_session(
        "generic_mvp",
        ["p1"],
        player_cards=build_player_cards(["p1"]),
    )
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
    runtime = _runtime_with_deterministic_success()
    session = runtime.create_session(
        "generic_mvp",
        ["p1"],
        player_cards=build_player_cards(["p1"]),
    )
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
    runtime = _runtime_with_deterministic_success()
    session = runtime.create_session(
        "tokoyami_subset",
        ["p1"],
        player_cards=build_player_cards(["p1"]),
    )
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
    runtime = _runtime_with_deterministic_success()
    session = runtime.create_session(
        "tokoyami_subset",
        ["p1"],
        player_cards=build_player_cards(["p1"]),
    )
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
    runtime = _runtime_with_deterministic_success()
    session = runtime.create_session(
        "tokoyami_subset",
        ["p1", "p2"],
        player_cards=build_player_cards(["p1", "p2"]),
    )
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


# ---------------------------------------------------------------------------
# _init_npc_states 幂等性测试（GROUP-7 / TASK-010）
# ---------------------------------------------------------------------------


def test_init_idempotent_raises_on_double_call() -> None:
    """对同一会话重复调用 _init_npc_states 应抛出 RuntimeError。"""
    runtime = _runtime_with_deterministic_success()
    session = runtime.create_session(
        "tokoyami_subset",
        ["p1"],
        player_cards=build_player_cards(["p1"]),
    )

    # 第一次调用已在 create_session 中完成，此时 npc_states 应非空。
    assert session.npc_states

    # 再次直接调用 helper 应触发幂等保护。
    module = runtime._load_module(session.module_id)
    with pytest.raises(RuntimeError, match="禁止重复调用"):
        runtime._init_npc_states(module, session, player_ids=["p1"])


# ---------------------------------------------------------------------------
# ENGINE-001：resolve_turn 排空 npc_patch_queue
# ---------------------------------------------------------------------------


def test_resolve_turn_drains_npc_patch_queue() -> None:
    """清空附带 producer='session_init' 的补丁队列并写入 current_scene_id。"""
    runtime = _runtime_with_deterministic_success()
    player_ids = ["p1", "p2"]
    session = runtime.create_session(
        "tokoyami_subset",
        player_ids,
        player_cards=build_player_cards(player_ids),
    )

    # 助手初始在 car_4 (default_scene_id)，写个旧值一致的补丁。
    attendant = session.npc_states["attendant"]
    old_scene_id = attendant.current_scene_id
    patched_scene_id = "car_3"
    session.npc_patch_queue.append(
        NPCStatePatchProposal(
            npc_id="attendant",
            path="current_scene_id",
            old_value=old_scene_id,
            new_value=patched_scene_id,
            reason="test phase-A patch",
            producer="session_init",
        )
    )

    # 空转一次（无玩家意图仅推进时钟 / 排空队列）。
    asyncio.run(runtime.resolve_turn(session.session_id))

    assert session.npc_patch_queue == [], "补丁队列应在 resolve_turn 后排空"
    assert (
        session.npc_states["attendant"].current_scene_id == patched_scene_id
    ), "accept 的补丁应写回 npc_states"


# ---------------------------------------------------------------------------
# ENGINE-002：visible_to_player_ids 由 npc.visibility 决定
# ---------------------------------------------------------------------------


def test_create_session_seeds_public_npc_visible_to_all_players() -> None:
    """tokoyami_subset 的 attendant 是 public → 所有玩家可见。"""
    runtime = _runtime_with_deterministic_success()
    player_ids = ["p1", "p2"]
    session = runtime.create_session(
        "tokoyami_subset",
        player_ids,
        player_cards=build_player_cards(player_ids),
    )

    assert (
        session.npc_states["attendant"].visible_to_player_ids == set(player_ids)
    ), "public NPC 应对所有玩家可见"


def test_create_session_seeds_keeper_npc_invisible_to_players() -> None:
    """visibility='keeper' 的 NPC 对玩家不可见（仅守密人）。"""
    runtime = _runtime_with_deterministic_success()
    player_ids = ["p1", "p2"]
    session = runtime.create_session(
        "tokoyami_subset",
        player_ids,
        player_cards=build_player_cards(player_ids),
    )

    module = runtime._load_module(session.module_id)
    # 模拟 visibility=keeper 的行为：重跑 _init_npc_states 之前修改模块。
    for npc in module.narrative_context.npcs:
        if npc.id == "attendant":
            npc.visibility = "keeper"
    # 重置 session 状态以便重复初始化
    session.npc_states.clear()
    runtime._init_npc_states(module, session, player_ids=player_ids)

    assert (
        session.npc_states["attendant"].visible_to_player_ids == set()
    ), "keeper NPC 不应对任何玩家可见"

from __future__ import annotations

import asyncio

from scenario.runtime import RuntimeEvent, SceneRuntime, TurnResolution

from tests.scene.card_fixtures import build_player_cards


def _submit_and_resolve(
    runtime: SceneRuntime,
    *,
    session_id: str,
    intent: dict[str, object],
) -> TurnResolution:
    runtime.submit_intent(session_id, "p1", intent)
    return asyncio.run(runtime.resolve_turn(session_id))


def _events(resolution: TurnResolution, event_type: str) -> list[RuntimeEvent]:
    return [event for event in resolution.event_log if event.type == event_type]


def test_consecutive_off_map_moves_trigger_major_then_severe_penalties() -> None:
    runtime = SceneRuntime()
    session = runtime.create_session(
        "generic_mvp",
        ["p1"],
        player_cards=build_player_cards(["p1"]),
    )

    first = _submit_and_resolve(
        runtime,
        session_id=session.session_id,
        intent={"type": "move", "target_scene_id": "exit"},
    )
    first_outcome = first.scene_batches[0].outcomes[0]

    assert first_outcome.success is False
    assert first_outcome.reason_code == "no_link"
    assert first_outcome.violation_kind == "off_map_move"
    assert first_outcome.penalty_tier == "warning"
    assert session.player_states["p1"].current_scene_id == "foyer"

    second = _submit_and_resolve(
        runtime,
        session_id=session.session_id,
        intent={"type": "move", "target_scene_id": "exit"},
    )
    second_penalties = _events(second, "movement_penalty_triggered")

    assert second_penalties
    assert second_penalties[0].penalty_tier == "major_penalty"
    assert second_penalties[0].reason_code == "no_link"
    assert second_penalties[0].required_threshold == 7
    assert session.player_states["p1"].illegal_move_risk.consecutive_count == 2

    third = _submit_and_resolve(
        runtime,
        session_id=session.session_id,
        intent={"type": "move", "target_scene_id": "exit"},
    )
    third_penalties = _events(third, "movement_penalty_triggered")

    assert third_penalties
    assert third_penalties[0].penalty_tier == "severe_penalty"
    assert session.player_states["p1"].illegal_move_risk.severe_triggered is True


def test_intermittent_off_map_moves_still_trigger_major_penalty_after_decay() -> None:
    runtime = SceneRuntime()
    session = runtime.create_session(
        "generic_mvp",
        ["p1"],
        player_cards=build_player_cards(["p1"]),
    )

    _submit_and_resolve(
        runtime,
        session_id=session.session_id,
        intent={"type": "move", "target_scene_id": "exit"},
    )
    legal_move = _submit_and_resolve(
        runtime,
        session_id=session.session_id,
        intent={"type": "move", "target_scene_id": "storage"},
    )
    decay_events = [
        event
        for event in _events(legal_move, "movement_risk_updated")
        if event.reason_code == "risk_decay"
    ]

    assert decay_events
    assert decay_events[0].decay_applied == 1

    _submit_and_resolve(
        runtime,
        session_id=session.session_id,
        intent={"type": "move", "target_scene_id": "control"},
    )
    _submit_and_resolve(
        runtime,
        session_id=session.session_id,
        intent={"type": "move", "target_scene_id": "foyer"},
    )
    major = _submit_and_resolve(
        runtime,
        session_id=session.session_id,
        intent={"type": "move", "target_scene_id": "exit"},
    )

    penalties = _events(major, "movement_penalty_triggered")
    assert penalties
    assert penalties[0].penalty_tier == "major_penalty"
    assert session.player_states["p1"].illegal_move_risk.recent_window_count == 3


def test_missing_flag_or_stage_blocked_moves_do_not_count_as_off_map_move() -> None:
    runtime = SceneRuntime()
    session = runtime.create_session(
        "generic_mvp",
        ["p1"],
        player_cards=build_player_cards(["p1"]),
    )

    missing_flag = _submit_and_resolve(
        runtime,
        session_id=session.session_id,
        intent={"type": "move", "target_scene_id": "control"},
    )
    missing_flag_outcome = missing_flag.scene_batches[0].outcomes[0]

    assert missing_flag_outcome.success is False
    assert missing_flag_outcome.reason_code == "missing_flags"
    assert missing_flag_outcome.violation_kind == ""
    assert session.player_states["p1"].illegal_move_risk.total_count == 0
    assert not _events(missing_flag, "movement_risk_updated")

    session.global_flags.add("door_unlocked")
    missing_stage = _submit_and_resolve(
        runtime,
        session_id=session.session_id,
        intent={"type": "move", "target_scene_id": "control"},
    )
    missing_stage_outcome = missing_stage.scene_batches[0].outcomes[0]

    assert missing_stage_outcome.success is False
    assert missing_stage_outcome.reason_code == "missing_stage"
    assert missing_stage_outcome.violation_kind == ""
    assert session.player_states["p1"].illegal_move_risk.total_count == 0
    assert not _events(missing_stage, "movement_risk_updated")

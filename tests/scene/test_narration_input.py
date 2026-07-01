from __future__ import annotations

from scenario.narration import NarrativeState, build_narration_input_packet
from scenario.runtime import RuntimeEvent, SceneRuntime

from tests.scene.card_fixtures import build_player_cards, resolve_turn_sync


def test_input_packet_uses_committed_resolution_and_does_not_mutate_session() -> None:
    runtime = SceneRuntime(roll_provider=lambda: 1)
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
    resolution = resolve_turn_sync(runtime, session.session_id)
    before = session.model_dump(mode="json")
    module = runtime._load_module(session.module_id)  # noqa: SLF001

    packet = build_narration_input_packet(
        resolution=resolution,
        session=session,
        module=module,
        narrative_state=NarrativeState(scene_mood={"foyer": "quiet"}),
        forbidden_facts=["secret-door"],
    )
    packet_again = build_narration_input_packet(
        resolution=resolution,
        session=session,
        module=module,
        narrative_state=packet.narrative_state,
        forbidden_facts=["secret-door"],
    )

    assert session.model_dump(mode="json") == before
    assert packet.session_id == session.session_id
    assert packet.turn_no == resolution.turn_no
    assert packet.player_scene_snapshots[0].current_scene_id == "storage"
    assert any(diff.kind == "movement" for diff in packet.state_diffs)
    assert packet.forbidden_facts == ["secret-door"]
    assert {scene.scene_id for scene in packet.static_scene_context} == {
        "foyer",
        "storage",
    }
    assert [ref.event_id for ref in packet.event_refs] == [
        ref.event_id for ref in packet_again.event_refs
    ]
    assert "event_id" not in RuntimeEvent.model_fields

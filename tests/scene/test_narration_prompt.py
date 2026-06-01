from __future__ import annotations

from scenario.narration import (
    NarrationPromptBuilder,
    VectorMemory,
    VectorMemoryMetadata,
    build_narration_input_packet,
)
from scenario.runtime import SceneRuntime

from tests.scene.card_fixtures import build_player_cards, resolve_turn_sync


def _packet_with_check():
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
    resolve_turn_sync(runtime, session.session_id)
    runtime.submit_intent(
        session.session_id,
        "p1",
        {"type": "action", "action_id": "find_key"},
    )
    resolution = resolve_turn_sync(runtime, session.session_id)
    return build_narration_input_packet(
        resolution=resolution,
        session=session,
        module=runtime._load_module(session.module_id),  # noqa: SLF001
        forbidden_facts=["uncommitted-secret"],
    )


def test_tiny_budget_preserves_required_layers_and_trims_auxiliary_memory() -> None:
    packet = _packet_with_check()
    memory = VectorMemory(
        metadata=VectorMemoryMetadata(
            memory_id="m-atmosphere",
            source_turn=1,
            kind="scene",
        ),
        summary_text="A" * 2000,
    )

    result = NarrationPromptBuilder().build(
        packet,
        memories=[memory],
        max_chars=50,
    )

    assert "Permanent rules" in result.prompt
    assert packet.event_refs[0].event_id in result.prompt
    assert "find_key" in result.prompt
    assert "uncommitted-secret" in result.prompt
    assert "Output schema" in result.prompt
    assert "auxiliary_vector_memory" in result.omitted_layers
    assert "A" * 100 not in result.prompt

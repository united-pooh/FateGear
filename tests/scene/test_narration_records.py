from __future__ import annotations

from scenario.narration import (
    KeeperNarrationDraft,
    ModelMetadata,
    NarrationPromptBuilder,
    NarrationValidator,
    build_narration_input_packet,
    build_narration_record,
)
from scenario.runtime import RuntimeEvent, SceneRuntime, TurnResolution

from tests.scene.card_fixtures import build_player_cards


def _packet():
    runtime = SceneRuntime()
    session = runtime.create_session(
        "generic_mvp",
        ["p1"],
        player_cards=build_player_cards(["p1"]),
    )
    resolution = TurnResolution(
        session_id=session.session_id,
        turn_no=1,
        next_turn=2,
        event_log=[RuntimeEvent(type="turn_started", turn_no=1, message="开始")],
    )
    return build_narration_input_packet(
        resolution=resolution,
        session=session,
        module=runtime._load_module(session.module_id),  # noqa: SLF001
    )


def test_record_generation_is_deterministic_and_auditable() -> None:
    packet = _packet()
    draft = KeeperNarrationDraft(
        public_text="公开叙事。",
        source_event_ids=[packet.event_refs[0].event_id],
        cited_memory_ids=[],
    )
    validation = NarrationValidator().validate(draft, packet, [])
    prompt = NarrationPromptBuilder().build(packet)
    metadata = ModelMetadata(provider="test", model="static")

    record = build_narration_record(
        packet=packet,
        validation=validation,
        prompt=prompt,
        model_metadata=metadata,
    )
    record_again = build_narration_record(
        packet=packet,
        validation=validation,
        prompt=prompt,
        model_metadata=metadata,
    )

    assert record.record_id == record_again.record_id
    assert record.final_public_text == "公开叙事。"
    assert record.source_event_ids == [packet.event_refs[0].event_id]
    assert record.model_metadata.provider == "test"
    assert record.log_summary["used_event_ids"] == [packet.event_refs[0].event_id]
    assert record.replay_input["draft"]["public_text"] == "公开叙事。"

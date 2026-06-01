from __future__ import annotations

from scenario.narration import (
    KeeperNarrationDraft,
    NarrationPatchProposal,
    NarrationValidator,
    NarrativeState,
    VectorMemory,
    VectorMemoryMetadata,
    build_narration_input_packet,
)
from scenario.narration.contracts import NarrationInputPacket
from scenario.runtime import SceneRuntime

from tests.scene.card_fixtures import build_player_cards, resolve_turn_sync


def _failed_check_packet() -> NarrationInputPacket:
    runtime = SceneRuntime(roll_provider=lambda: 99)
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
        narrative_state=NarrativeState(),
        forbidden_facts=["sealed-secret"],
    )


def _move_to_storage_packet() -> NarrationInputPacket:
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
    return build_narration_input_packet(
        resolution=resolution,
        session=session,
        module=runtime._load_module(session.module_id),  # noqa: SLF001
    )


def _primed_machine_packet() -> NarrationInputPacket:
    runtime = SceneRuntime(roll_provider=lambda: 1)
    session = runtime.create_session(
        "generic_mvp",
        ["p1"],
        player_cards=build_player_cards(["p1"]),
    )
    intents: tuple[dict[str, object], ...] = (
        {"type": "move", "target_scene_id": "storage"},
        {"type": "action", "action_id": "find_key"},
        {"type": "action", "action_id": "unlock_control_door"},
        {"type": "move", "target_scene_id": "foyer"},
        {"type": "move", "target_scene_id": "control"},
    )
    for intent in intents:
        runtime.submit_intent(session.session_id, "p1", intent)
        resolve_turn_sync(runtime, session.session_id)
    runtime.submit_intent(
        session.session_id,
        "p1",
        {"type": "action", "action_id": "prime_machine"},
    )
    resolution = resolve_turn_sync(runtime, session.session_id)
    return build_narration_input_packet(
        resolution=resolution,
        session=session,
        module=runtime._load_module(session.module_id),  # noqa: SLF001
    )


def test_validator_falls_back_on_failed_check_contradiction_and_forbidden_fact() -> None:
    packet = _failed_check_packet()
    draft = KeeperNarrationDraft(
        public_text="搜索钥匙成功完成，sealed-secret 也被公开。",
        source_event_ids=[packet.event_refs[0].event_id],
    )

    result = NarrationValidator().validate(draft, packet, [])

    assert result.fallback_used is True
    assert result.accepted_patches == []
    assert any("forbidden fact" in reason for reason in result.fallback_reasons)
    assert any("failed check" in reason for reason in result.fallback_reasons)
    assert "sealed-secret" not in result.final_draft.public_text


def test_validator_rejects_invalid_memory_citation_and_vector_authority() -> None:
    packet = _failed_check_packet()
    memory = VectorMemory(
        metadata=VectorMemoryMetadata(memory_id="m1", source_turn=1, kind="narrative"),
        summary_text="安全气味延续。",
    )
    draft = KeeperNarrationDraft(
        public_text="根据记忆可以确定搜索钥匙成功。",
        source_event_ids=[packet.event_refs[0].event_id],
        cited_memory_ids=["missing-memory"],
    )

    result = NarrationValidator().validate(draft, packet, [memory])

    assert result.fallback_used is True
    assert any("invalid cited_memory_ids" in reason for reason in result.fallback_reasons)
    assert any("vector memory used" in reason for reason in result.fallback_reasons)


def test_validator_schema_invalid_output_uses_safe_fallback() -> None:
    packet = _failed_check_packet()

    result = NarrationValidator().validate({"npc_lines": []}, packet, [])

    assert result.fallback_used is True
    assert result.accepted_patches == []
    assert result.final_draft.source_event_ids == [ref.event_id for ref in packet.event_refs]


def test_validator_accepts_valid_patch_and_audits_rejected_patch_without_fallback() -> None:
    packet = _failed_check_packet()
    good_patch = NarrationPatchProposal(
        path="scene_mood.storage",
        old_value=None,
        new_value="潮湿而沉默",
        reason="Committed failed search supports a subdued mood.",
        source_event_ids=[packet.event_refs[0].event_id],
    )
    bad_patch = NarrationPatchProposal(
        path="story_state.current_stage_id",
        old_value="setup",
        new_value="escaped",
        reason="Illegal authority write.",
        source_event_ids=[packet.event_refs[0].event_id],
    )
    draft = KeeperNarrationDraft(
        public_text="搜索钥匙没有结果，储藏室安静下来。",
        patch_proposals=[good_patch, bad_patch],
        source_event_ids=[packet.event_refs[0].event_id],
    )

    result = NarrationValidator().validate(draft, packet, [])

    assert result.fallback_used is False
    assert result.accepted_patches == [good_patch]
    assert result.updated_state.scene_mood["storage"] == "潮湿而沉默"
    assert result.rejected_patches[0].path == "story_state.current_stage_id"


def test_validator_rejects_movement_diff_contradiction() -> None:
    packet = _move_to_storage_packet()
    draft = KeeperNarrationDraft(
        public_text="玩家 p1 仍在 foyer，没有进入 storage。",
        source_event_ids=[packet.event_refs[0].event_id],
    )

    result = NarrationValidator().validate(draft, packet, [])

    assert result.fallback_used is True
    assert any("movement" in reason for reason in result.fallback_reasons)


def test_validator_rejects_story_clock_and_completed_action_contradictions() -> None:
    packet = _primed_machine_packet()
    draft = KeeperNarrationDraft(
        public_text=(
            "prime_machine 没有完成，alarm 没有推进，"
            "剧情仍在 access_opened，没有进入 system_primed。"
        ),
        source_event_ids=[packet.event_refs[0].event_id],
    )

    result = NarrationValidator().validate(draft, packet, [])

    assert result.fallback_used is True
    assert any("completed action" in reason for reason in result.fallback_reasons)
    assert any("clock change" in reason for reason in result.fallback_reasons)
    assert any("story transition" in reason for reason in result.fallback_reasons)

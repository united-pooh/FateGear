from __future__ import annotations

from scenario.narration import (
    KeeperNarrationDraft,
    ModelMetadata,
    NarrationPatchProposal,
    VectorMemory,
    VectorMemoryMetadata,
    build_narration_input_packet,
    replay_narration_record,
)
from scenario.narration.contracts import NarrationInputPacket
from scenario.runtime import SceneRuntime

from tests.scene.card_fixtures import build_player_cards, resolve_turn_sync


def _move_to_storage_packet() -> tuple[NarrationInputPacket, NarrationInputPacket]:
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
    module = runtime._load_module(session.module_id)  # noqa: SLF001
    packet = build_narration_input_packet(
        resolution=resolution,
        session=session,
        module=module,
    )
    rebuilt_packet = build_narration_input_packet(
        resolution=resolution,
        session=session,
        module=module,
    )
    return packet, rebuilt_packet


def _failed_search_packet() -> tuple[NarrationInputPacket, NarrationInputPacket]:
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
    module = runtime._load_module(session.module_id)  # noqa: SLF001
    packet = build_narration_input_packet(
        resolution=resolution,
        session=session,
        module=module,
    )
    rebuilt_packet = build_narration_input_packet(
        resolution=resolution,
        session=session,
        module=module,
    )
    return packet, rebuilt_packet


def _first_event_id(packet: NarrationInputPacket) -> str:
    return packet.event_refs[0].event_id


def _find_key_event_id(packet: NarrationInputPacket) -> str:
    for event_ref in packet.event_refs:
        event = event_ref.runtime_event
        if event.type == "action_resolved" and event.action_id == "find_key":
            return event_ref.event_id
    raise AssertionError("find_key action event was not captured")


def _authoritative_snapshot(packet: NarrationInputPacket) -> dict[str, object]:
    return {
        "story": packet.story_snapshot.model_dump(mode="json"),
        "scenes": [scene.model_dump(mode="json") for scene in packet.scene_snapshots],
        "rules": [fact.model_dump(mode="json") for fact in packet.rule_facts],
        "checks": [check.model_dump(mode="json") for check in packet.check_results],
        "state_diffs": [diff.model_dump(mode="json") for diff in packet.state_diffs],
    }


def test_replay_record_is_deterministic_for_accepted_public_patch() -> None:
    packet, rebuilt_packet = _move_to_storage_packet()
    event_id = _first_event_id(packet)
    memory = VectorMemory(
        metadata=VectorMemoryMetadata(
            memory_id="mem-storage-scent",
            source_turn=1,
            source_event_ids=[event_id],
            kind="scene",
        ),
        summary_text="储藏室的空气潮湿，带有旧纸箱气味。",
    )
    patch = NarrationPatchProposal(
        path="scene_mood.storage",
        old_value=None,
        new_value="潮湿而谨慎",
        reason="Movement into storage sets a public scene mood.",
        source_event_ids=[event_id],
    )
    rejected_patch = NarrationPatchProposal(
        path="global_flags.key_found",
        old_value=False,
        new_value=True,
        reason="Replay must audit illegal authority writes.",
        source_event_ids=[event_id],
    )
    draft = KeeperNarrationDraft(
        public_text="玩家进入储藏室，潮湿的空气压低了声音。",
        patch_proposals=[patch, rejected_patch],
        source_event_ids=[event_id],
        cited_memory_ids=[memory.memory_id],
    )
    metadata = ModelMetadata(
        provider="test",
        model="static-renderer",
        response_id="resp-001",
        latency_ms=7,
    )
    authoritative_before = _authoritative_snapshot(packet)

    record = replay_narration_record(
        packet=packet,
        draft=draft,
        memories=[memory],
        model_metadata=metadata,
    )
    replayed = replay_narration_record(
        packet=packet,
        draft=draft,
        memories=[memory],
        model_metadata=metadata,
    )
    rebuilt = replay_narration_record(
        packet=rebuilt_packet,
        draft=draft,
        memories=[memory],
        model_metadata=metadata,
    )

    assert [ref.event_id for ref in packet.event_refs] == [
        ref.event_id for ref in rebuilt_packet.event_refs
    ]
    assert record.model_dump(mode="json") == replayed.model_dump(mode="json")
    assert record.model_dump(mode="json") == rebuilt.model_dump(mode="json")
    assert record.fallback_used is False
    assert record.accepted_patches == [patch]
    assert [audit.path for audit in record.rejected_patches] == ["global_flags.key_found"]
    assert any("authoritative" in warning for warning in record.validation_warnings)
    assert record.cited_memory_ids == [memory.memory_id]
    assert set(draft.source_event_ids) <= packet.event_ids
    assert set(record.source_event_ids) <= packet.event_ids
    assert record.source_event_ids == draft.source_event_ids
    assert record.model_metadata == metadata
    assert record.prompt_layer_summaries
    assert record.replay_input["draft"]["public_text"] == draft.public_text
    assert _authoritative_snapshot(packet) == authoritative_before


def test_replay_record_is_deterministic_for_safe_fallback() -> None:
    packet, rebuilt_packet = _failed_search_packet()
    event_id = _find_key_event_id(packet)
    draft = KeeperNarrationDraft(
        public_text="玩家 p1 执行动作「搜索钥匙」成功完成，key_found 已经成立。",
        source_event_ids=[event_id],
    )
    metadata = ModelMetadata(provider="test", model="static-renderer")
    authoritative_before = _authoritative_snapshot(packet)

    record = replay_narration_record(
        packet=packet,
        draft=draft,
        model_metadata=metadata,
    )
    rebuilt = replay_narration_record(
        packet=rebuilt_packet,
        draft=draft,
        model_metadata=metadata,
    )

    assert record.model_dump(mode="json") == rebuilt.model_dump(mode="json")
    assert record.fallback_used is True
    assert record.accepted_patches == []
    assert record.rejected_patches == []
    assert record.validation_warnings == record.fallback_reasons
    assert set(draft.source_event_ids) <= packet.event_ids
    assert set(record.source_event_ids) <= packet.event_ids
    assert record.source_event_ids == [ref.event_id for ref in packet.event_refs]
    assert record.model_metadata == metadata
    assert record.prompt_layer_summaries
    assert "成功完成" not in record.final_public_text
    assert any("failed check" in reason for reason in record.fallback_reasons)
    assert _authoritative_snapshot(packet) == authoritative_before

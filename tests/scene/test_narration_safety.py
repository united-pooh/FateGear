from __future__ import annotations

from scenario.narration import (
    InMemoryVectorContextStore,
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


def _failed_search_packet(
    *,
    narrative_state: NarrativeState | None = None,
    forbidden_facts: list[str] | None = None,
) -> NarrationInputPacket:
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
        narrative_state=narrative_state or NarrativeState(),
        forbidden_facts=forbidden_facts or [],
    )


def _find_key_event_id(packet: NarrationInputPacket) -> str:
    for event_ref in packet.event_refs:
        event = event_ref.runtime_event
        if event.type == "action_resolved" and event.action_id == "find_key":
            return event_ref.event_id
    raise AssertionError("find_key action event was not captured")


def test_failed_check_contradiction_uses_safe_committed_fallback() -> None:
    packet = _failed_search_packet()
    event_id = _find_key_event_id(packet)
    draft = KeeperNarrationDraft(
        public_text="玩家 p1 执行动作「搜索钥匙」成功完成，key_found 已经成立。",
        source_event_ids=[event_id],
    )

    result = NarrationValidator().validate(draft, packet, [])

    assert result.fallback_used is True
    assert result.accepted_patches == []
    assert any("failed check" in reason for reason in result.fallback_reasons)
    assert "成功完成" not in result.final_draft.public_text
    assert "key_found 已经成立" not in result.final_draft.public_text
    assert "失败" in result.final_draft.public_text
    assert result.final_draft.source_event_ids == [
        event_ref.event_id for event_ref in packet.event_refs
    ]


def test_forbidden_fact_leakage_is_redacted_by_safe_fallback() -> None:
    packet = _failed_search_packet(forbidden_facts=["hidden-basement"])
    event_id = _find_key_event_id(packet)
    draft = KeeperNarrationDraft(
        public_text="搜索钥匙没有结果，但 hidden-basement 入口在箱子后方。",
        source_event_ids=[event_id],
    )

    result = NarrationValidator().validate(draft, packet, [])

    assert result.fallback_used is True
    assert any("forbidden fact" in reason for reason in result.fallback_reasons)
    assert result.accepted_patches == []
    assert "hidden-basement" not in result.final_draft.public_text
    assert result.final_draft.style_notes == ["safe_template_fallback"]


def test_vector_memory_conflict_is_filtered_and_cannot_be_cited() -> None:
    packet = _failed_search_packet(forbidden_facts=["hidden-basement"])
    event_id = _find_key_event_id(packet)
    conflicting_memory = VectorMemory(
        metadata=VectorMemoryMetadata(
            memory_id="mem-conflicting-find-key",
            source_turn=1,
            source_event_ids=[event_id],
            kind="narrative",
        ),
        summary_text="搜索钥匙成功完成，并且 hidden-basement 已经公开。",
    )
    safe_memory = VectorMemory(
        metadata=VectorMemoryMetadata(
            memory_id="mem-safe-storage-air",
            source_turn=1,
            kind="scene",
            confidence=0.5,
        ),
        summary_text="储藏室仍然潮湿、拥挤。",
    )
    store = InMemoryVectorContextStore([conflicting_memory, safe_memory])
    draft = KeeperNarrationDraft(
        public_text="搜索钥匙没有结果，空气里的霉味延续下来。",
        source_event_ids=[event_id],
        cited_memory_ids=[conflicting_memory.memory_id],
    )

    result = NarrationValidator().validate(draft, packet, [conflicting_memory])

    assert store.retrieve(packet) == [safe_memory]
    assert result.fallback_used is True
    assert any("conflicts with committed facts" in reason for reason in result.fallback_reasons)
    assert result.final_draft.cited_memory_ids == []


def test_patch_validation_accepts_public_state_and_rejects_authority_writes() -> None:
    packet = _failed_search_packet(
        narrative_state=NarrativeState(scene_mood={"storage": "安静"})
    )
    authoritative_before = {
        "story": packet.story_snapshot.model_dump(mode="json"),
        "scenes": [scene.model_dump(mode="json") for scene in packet.scene_snapshots],
        "rules": [fact.model_dump(mode="json") for fact in packet.rule_facts],
        "checks": [check.model_dump(mode="json") for check in packet.check_results],
    }
    event_id = _find_key_event_id(packet)
    accepted_patch = NarrationPatchProposal(
        path="public_observations.key_search",
        old_value=None,
        new_value="钥匙线索没有出现。",
        reason="The failed committed check supports a public observation.",
        source_event_ids=[event_id],
    )
    stale_patch = NarrationPatchProposal(
        path="scene_mood.storage",
        old_value=None,
        new_value="紧张",
        reason="The old value no longer matches.",
        source_event_ids=[event_id],
    )
    authoritative_patch = NarrationPatchProposal(
        path="check_results.find_key.success",
        old_value=False,
        new_value=True,
        reason="Illegal attempt to rewrite a failed check.",
        source_event_ids=[event_id],
    )
    draft = KeeperNarrationDraft(
        public_text="搜索钥匙没有结果，储藏室继续保持安静。",
        patch_proposals=[accepted_patch, stale_patch, authoritative_patch],
        source_event_ids=[event_id],
    )

    result = NarrationValidator().validate(draft, packet, [])

    assert result.fallback_used is False
    assert result.accepted_patches == [accepted_patch]
    assert result.updated_state.public_observations["key_search"] == "钥匙线索没有出现。"
    assert result.updated_state.scene_mood["storage"] == "安静"
    assert [patch.path for patch in result.rejected_patches] == [
        "scene_mood.storage",
        "check_results.find_key.success",
    ]
    assert "old_value" in result.rejected_patches[0].reason
    assert "authoritative" in result.rejected_patches[1].reason
    assert "check_results" not in result.updated_state.model_dump(mode="json")
    assert authoritative_before == {
        "story": packet.story_snapshot.model_dump(mode="json"),
        "scenes": [scene.model_dump(mode="json") for scene in packet.scene_snapshots],
        "rules": [fact.model_dump(mode="json") for fact in packet.rule_facts],
        "checks": [check.model_dump(mode="json") for check in packet.check_results],
    }


def test_schema_invalid_output_falls_back_without_applying_patches() -> None:
    packet = _failed_search_packet()

    result = NarrationValidator().validate({"npc_lines": []}, packet, [])

    assert result.fallback_used is True
    assert result.accepted_patches == []
    assert result.rejected_patches == []
    assert result.final_draft.patch_proposals == []
    assert result.final_draft.style_notes == ["safe_template_fallback"]
    assert result.final_draft.source_event_ids == [
        event_ref.event_id for event_ref in packet.event_refs
    ]

from __future__ import annotations

import pytest

from scenario.narration import (
    KeeperNarrationDraft,
    KeeperNarrationRecord,
    ModelMetadata,
    NarrationPatchProposal,
    NarrativeState,
    NpcLine,
    PromptLayerSummary,
    RejectedPatchAudit,
)


def test_narrative_state_excludes_authoritative_runtime_fields() -> None:
    fields = set(NarrativeState.model_fields)

    assert "scene_mood" in fields
    assert "npc_attitudes" in fields
    assert "story_state" not in fields
    assert "global_flags" not in fields
    assert "clock_values" not in fields
    assert "completed_actions" not in fields
    assert "check_results" not in fields

    with pytest.raises(ValueError):
        NarrativeState(story_state={"current_stage_id": "setup"})


def test_patch_draft_and_record_contracts_serialize_public_scope() -> None:
    proposal = NarrationPatchProposal(
        path="scene_mood.foyer",
        old_value=None,
        new_value="冷光压低了前厅的安全感",
        reason="Use the committed foyer event to set public tone.",
        source_event_ids=["e1"],
        confidence=0.8,
    )
    draft = KeeperNarrationDraft(
        public_text="前厅的灯光轻轻闪烁。",
        npc_lines=[NpcLine(speaker_id="guard", text="这里不太对劲。")],
        keeper_notes=["public only"],
        patch_proposals=[proposal],
        source_event_ids=["e1", "e1"],
        cited_memory_ids=["m1", "m1"],
        style_notes=["quiet"],
    )
    record = KeeperNarrationRecord(
        record_id="knr_test",
        session_id="s1",
        turn_no=1,
        final_public_text=draft.public_text,
        npc_lines=draft.npc_lines,
        keeper_notes=draft.keeper_notes,
        accepted_patches=[proposal],
        rejected_patches=[
            RejectedPatchAudit(
                path="global_flags.key_found",
                reason="patch targets authoritative runtime state",
                proposal=proposal.model_copy(update={"path": "global_flags.key_found"}),
            )
        ],
        source_event_ids=draft.source_event_ids,
        cited_memory_ids=draft.cited_memory_ids,
        model_metadata=ModelMetadata(provider="test", model="static"),
        prompt_layer_summaries=[
            PromptLayerSummary(name="authoritative_facts", required=True, char_count=10)
        ],
    )

    payload = record.model_dump(mode="json")

    assert proposal.scope == "public"
    assert draft.source_event_ids == ["e1"]
    assert draft.cited_memory_ids == ["m1"]
    assert payload["accepted_patches"][0]["path"] == "scene_mood.foyer"
    assert payload["rejected_patches"][0]["reason"] == "patch targets authoritative runtime state"

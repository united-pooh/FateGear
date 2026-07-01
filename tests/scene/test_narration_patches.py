from __future__ import annotations

from scenario.narration import (
    NarrationPatchProposal,
    NarrativeState,
    build_event_refs,
    validate_and_apply_patches,
)
from scenario.runtime import RuntimeEvent, TurnResolution


def _event_refs():
    resolution = TurnResolution(
        session_id="s1",
        turn_no=1,
        next_turn=2,
        event_log=[
            RuntimeEvent(
                type="turn_started",
                turn_no=1,
                message="第 1 回合开始",
            ),
            RuntimeEvent(
                type="action_resolved",
                turn_no=1,
                message="玩家 p1 执行动作成功",
                player_id="p1",
                action_id="find_key",
                action_name="搜索钥匙",
                success=True,
            ),
        ],
    )
    return build_event_refs(resolution)


def test_accepts_allowlisted_public_narrative_state_patch() -> None:
    event_refs = _event_refs()
    state = NarrativeState()
    proposal = NarrationPatchProposal(
        path="scene_mood.foyer",
        old_value=None,
        new_value="空气里有轻微电流味",
        reason="Reflect the public event tone.",
        source_event_ids=[event_refs[1].event_id],
    )

    result = validate_and_apply_patches(state, [proposal], event_refs)

    assert result.rejected_patches == []
    assert result.accepted_patches == [proposal]
    assert result.state.scene_mood["foyer"] == "空气里有轻微电流味"
    assert state.scene_mood == {}


def test_rejects_old_value_mismatch_authoritative_path_and_unknown_event() -> None:
    event_refs = _event_refs()
    state = NarrativeState(scene_mood={"foyer": "安静"})
    proposals = [
        NarrationPatchProposal(
            path="scene_mood.foyer",
            old_value=None,
            new_value="紧张",
            reason="Wrong old value.",
            source_event_ids=[event_refs[0].event_id],
        ),
        NarrationPatchProposal(
            path="global_flags.key_found",
            old_value=False,
            new_value=True,
            reason="Illegal authoritative mutation.",
            source_event_ids=[event_refs[0].event_id],
        ),
        NarrationPatchProposal(
            path="npc_attitudes.guard",
            old_value=None,
            new_value="戒备",
            reason="Unknown event source.",
            source_event_ids=["missing-event"],
        ),
        NarrationPatchProposal(
            path="continuity_notes",
            old_value=[],
            new_value="not-a-list",
            reason="Wrong list value.",
            source_event_ids=[event_refs[0].event_id],
        ),
    ]

    result = validate_and_apply_patches(state, proposals, event_refs)

    assert result.accepted_patches == []
    assert [item.path for item in result.rejected_patches] == [
        "scene_mood.foyer",
        "global_flags.key_found",
        "npc_attitudes.guard",
        "continuity_notes",
    ]
    assert "old_value" in result.rejected_patches[0].reason
    assert "authoritative" in result.rejected_patches[1].reason
    assert "do not resolve" in result.rejected_patches[2].reason
    assert "list[str]" in result.rejected_patches[3].reason


def test_rejects_scope_allowlist_and_range_limits_without_mutating_state() -> None:
    event_refs = _event_refs()
    state = NarrativeState(scene_mood={"foyer": "安静"})
    before = state.model_dump(mode="json")
    proposals = [
        NarrationPatchProposal(
            path="scene_mood.foyer",
            old_value="安静",
            new_value="紧张",
            reason="Private narration is outside first-version scope.",
            source_event_ids=[event_refs[0].event_id],
            scope="private",
        ),
        NarrationPatchProposal(
            path="unknown_notes.foyer",
            old_value=None,
            new_value="不在 allowlist 里。",
            reason="Unknown public state root.",
            source_event_ids=[event_refs[0].event_id],
        ),
        NarrationPatchProposal(
            path="style_tags",
            old_value=[],
            new_value=[f"tag-{index}" for index in range(21)],
            reason="Too many style tags.",
            source_event_ids=[event_refs[0].event_id],
        ),
    ]

    result = validate_and_apply_patches(state, proposals, event_refs)

    assert result.accepted_patches == []
    assert [item.path for item in result.rejected_patches] == [
        "scene_mood.foyer",
        "unknown_notes.foyer",
        "style_tags",
    ]
    assert "public" in result.rejected_patches[0].reason
    assert "allowlisted" in result.rejected_patches[1].reason
    assert "too many" in result.rejected_patches[2].reason
    assert state.model_dump(mode="json") == before
    assert result.state.model_dump(mode="json") == before

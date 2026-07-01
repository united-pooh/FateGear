"""Validation and application for NarrativeState patches."""

from __future__ import annotations

from typing import Any

from .contracts import (
    NarrationEventRef,
    NarrationPatchProposal,
    NarrativeState,
    PatchApplicationResult,
    RejectedPatchAudit,
)
from .events import unresolved_event_ids


_MAP_PATHS = {
    "scene_mood",
    "npc_attitudes",
    "clue_emphasis",
    "public_observations",
}
_LIST_PATHS = {"continuity_notes", "style_tags"}
_AUTHORITATIVE_ROOTS = {
    "story_state",
    "story",
    "scene_instances",
    "scene_state",
    "scene_location",
    "player_states",
    "players",
    "global_flags",
    "flags",
    "clock_values",
    "clocks",
    "completed_actions",
    "triggered_clock_events",
    "pending_intents",
    "resolved_ending",
    "ending",
    "check_results",
    "turn_resolution",
    "runtime_event",
    "session",
}


def is_authoritative_path(path: str) -> bool:
    root = _root(path)
    return root in _AUTHORITATIVE_ROOTS


def is_allowed_narrative_path(path: str) -> bool:
    parts = _parts(path)
    if not parts:
        return False
    if parts[0] in _MAP_PATHS:
        return len(parts) == 2 and bool(parts[1])
    if parts[0] in _LIST_PATHS:
        return len(parts) == 1
    return False


def validate_patch(
    state: NarrativeState,
    proposal: NarrationPatchProposal,
    event_refs: list[NarrationEventRef],
) -> RejectedPatchAudit | None:
    reason = _patch_rejection_reason(state, proposal, event_refs)
    if reason is None:
        return None
    return RejectedPatchAudit(
        path=proposal.path,
        reason=reason,
        proposal=proposal,
    )


def apply_patch_to_state(
    state: NarrativeState,
    proposal: NarrationPatchProposal,
) -> NarrativeState:
    next_state = state.model_copy(deep=True)
    parts = _parts(proposal.path)
    root = parts[0]
    if root in _MAP_PATHS:
        target: dict[str, str] = getattr(next_state, root)
        target[parts[1]] = proposal.new_value
    elif root in _LIST_PATHS:
        setattr(next_state, root, list(proposal.new_value))
    return next_state


def validate_and_apply_patches(
    state: NarrativeState,
    proposals: list[NarrationPatchProposal],
    event_refs: list[NarrationEventRef],
) -> PatchApplicationResult:
    next_state = state.model_copy(deep=True)
    accepted: list[NarrationPatchProposal] = []
    rejected: list[RejectedPatchAudit] = []
    for proposal in proposals:
        rejection = validate_patch(next_state, proposal, event_refs)
        if rejection is not None:
            rejected.append(rejection)
            continue
        next_state = apply_patch_to_state(next_state, proposal)
        accepted.append(proposal)
    return PatchApplicationResult(
        state=next_state,
        accepted_patches=accepted,
        rejected_patches=rejected,
    )


def _patch_rejection_reason(
    state: NarrativeState,
    proposal: NarrationPatchProposal,
    event_refs: list[NarrationEventRef],
) -> str | None:
    if proposal.scope != "public":
        return "only public narration patches are supported"
    if is_authoritative_path(proposal.path):
        return "patch targets authoritative runtime state"
    if not is_allowed_narrative_path(proposal.path):
        return "path is not an allowlisted NarrativeState public path"
    if not proposal.source_event_ids:
        return "source_event_ids must reference current turn events"
    missing = unresolved_event_ids(proposal.source_event_ids, event_refs)
    if missing:
        return f"source_event_ids do not resolve: {missing}"
    current_value = _get_path_value(state, proposal.path)
    if current_value != proposal.old_value:
        return "old_value does not match current NarrativeState value"
    value_reason = _validate_new_value(proposal.path, proposal.new_value)
    if value_reason is not None:
        return value_reason
    return None


def _validate_new_value(path: str, value: Any) -> str | None:
    root = _root(path)
    if root in _MAP_PATHS:
        if not isinstance(value, str):
            return "map NarrativeState patches require string new_value"
        if len(value) > 400:
            return "string new_value is too long"
    if root in _LIST_PATHS:
        if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
            return "list NarrativeState patches require list[str] new_value"
        if len(value) > 20:
            return "list new_value has too many items"
        if any(len(item) > 400 for item in value):
            return "list item new_value is too long"
    return None


def _get_path_value(state: NarrativeState, path: str) -> Any:
    parts = _parts(path)
    root = parts[0]
    if root in _MAP_PATHS:
        return getattr(state, root).get(parts[1])
    if root in _LIST_PATHS:
        return list(getattr(state, root))
    return None


def _root(path: str) -> str:
    parts = _parts(path)
    return parts[0] if parts else ""


def _parts(path: str) -> list[str]:
    return [part for part in path.split(".") if part]

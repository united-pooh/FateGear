"""Filter layer for KTSL information authorization and redaction."""

from __future__ import annotations

from hashlib import sha1

from ..clues import PLAYER_VISIBLE_STATES, ClueGraph, SessionClueState
from .models import (
    ActorKnowledgeState,
    EventRecord,
    FilterDecision,
    InfoLabel,
    KTSLFixture,
    RunMode,
    ScheduleStep,
)

SENSITIVE_LEVELS = {"medium", "high", "keeper"}


def build_info_lookup(fixture: KTSLFixture) -> dict[str, InfoLabel]:
    """Return fixture info labels keyed by id."""

    return {info.id: info for info in fixture.info_labels}


def filter_fixture(
    fixture: KTSLFixture,
    run_mode: RunMode,
    schedule_steps: list[ScheduleStep] | None = None,
    *,
    clue_graph: ClueGraph | None = None,
    session_clues: SessionClueState | None = None,
) -> list[FilterDecision]:
    """Return per-event/per-character filter decisions."""

    step_event_ids = {
        step.event_id for step in schedule_steps or [] if step.status != "blocked"
    }
    events = [
        event
        for event in fixture.events
        if not step_event_ids or event.id in step_event_ids
    ]
    info_lookup = build_info_lookup(fixture)
    states = {state.character_id: state for state in fixture.initial_knowledge}

    decisions: list[FilterDecision] = []
    for event in events:
        for info_id in _event_info_ids(event):
            info = info_lookup.get(info_id)
            if info is None:
                continue
            for character_id in _relevant_character_ids(fixture, event, info):
                state = states.get(character_id)
                player_id = _player_id_for_character(fixture, event, character_id, state)
                decisions.append(
                    decide_info_access(
                        info=info,
                        event=event,
                        character_id=character_id,
                        player_id=player_id,
                        state=state,
                        run_mode=run_mode,
                        clue_graph=clue_graph,
                        session_clues=session_clues,
                    )
                )
    return decisions


def decide_info_access(
    *,
    info: InfoLabel,
    event: EventRecord,
    character_id: str,
    player_id: str,
    state: ActorKnowledgeState | None,
    run_mode: RunMode,
    clue_graph: ClueGraph | None = None,
    session_clues: SessionClueState | None = None,
) -> FilterDecision:
    """Classify one character's access to one event-linked info label."""

    authorized = _is_authorized(info, event, character_id, state)
    declassified = _is_declassified(info, character_id, run_mode)
    observed = _has_observed(info, event, player_id, state)
    sensitive = info.sensitivity in SENSITIVE_LEVELS
    clue_authorization_source = _clue_graph_authorization_source(
        info=info,
        player_id=player_id,
        clue_graph=clue_graph,
        session_clues=session_clues,
    )

    if declassified:
        return _decision(
            info,
            event,
            player_id,
            character_id,
            run_mode,
            status="declassified",
            declassified=True,
            reason_code="declassified",
        )
    if authorized:
        return _decision(
            info,
            event,
            player_id,
            character_id,
            run_mode,
            status="allowed",
            authorized=True,
            reason_code="authorized",
        )
    if clue_authorization_source:
        return _decision(
            info,
            event,
            player_id,
            character_id,
            run_mode,
            status="allowed",
            authorized=True,
            reason_code="clue_graph_authorized",
            reason=clue_authorization_source,
        )
    if info.kind == "obs" and observed and not sensitive:
        return _decision(
            info,
            event,
            player_id,
            character_id,
            run_mode,
            status="allowed",
            reason_code="observed_public_or_low",
        )
    if not sensitive:
        return _decision(
            info,
            event,
            player_id,
            character_id,
            run_mode,
            status="allowed",
            reason_code="public_or_low_sensitivity",
        )

    if run_mode == "ktsl_full":
        return FilterDecision(
            id=_decision_id(run_mode, event.id, info.id, character_id),
            run_mode=run_mode,
            info_id=info.id,
            event_id=event.id,
            player_id=player_id,
            character_id=character_id,
            status="redacted",
            redaction=info.redaction or event.redaction or "Sensitive information redacted.",
            reason_code="redacted_unauthorized_sensitive_info",
            reason="Unauthorized sensitive information was redacted without exposing private payload.",
        )

    leaked_public_payload = bool(info.public_payload or event.public_payload)
    return FilterDecision(
        id=_decision_id(run_mode, event.id, info.id, character_id),
        run_mode=run_mode,
        info_id=info.id,
        event_id=event.id,
        player_id=player_id,
        character_id=character_id,
        status="blocked",
        leaked_public_payload=leaked_public_payload,
        public_payload=info.public_payload if leaked_public_payload else "",
        reason_code="unauthorized_sensitive_public_payload",
        reason="Sensitive public payload is not authorized for this character in this run mode.",
    )


def declassification_completeness(
    fixture: KTSLFixture,
    run_mode: RunMode,
    decisions: list[FilterDecision] | None = None,
) -> float:
    """Return expected declassification pair coverage for the run mode."""

    expected_pairs = [
        (info.id, character_id)
        for info in fixture.info_labels
        if info.should_declassify or info.id in fixture.expected_declassified_info_ids
        for character_id in info.expected_declassified_for_character_ids
    ]
    if not expected_pairs:
        return 1.0

    if decisions is None:
        decisions = filter_fixture(fixture, run_mode)
    declassified_pairs = {
        (decision.info_id, decision.character_id)
        for decision in decisions
        if decision.status == "declassified" or decision.declassified
    }
    return len(set(expected_pairs) & declassified_pairs) / len(set(expected_pairs))


def _decision(
    info: InfoLabel,
    event: EventRecord,
    player_id: str,
    character_id: str,
    run_mode: RunMode,
    *,
    status: str,
    authorized: bool = False,
    declassified: bool = False,
    reason_code: str,
    reason: str = "",
) -> FilterDecision:
    return FilterDecision(
        id=_decision_id(run_mode, event.id, info.id, character_id),
        run_mode=run_mode,
        info_id=info.id,
        event_id=event.id,
        player_id=player_id,
        character_id=character_id,
        status=status,  # type: ignore[arg-type]
        authorized=authorized,
        declassified=declassified,
        public_payload=info.public_payload,
        reason_code=reason_code,
        reason=reason or reason_code.replace("_", " "),
    )


def _clue_graph_authorization_source(
    *,
    info: InfoLabel,
    player_id: str,
    clue_graph: ClueGraph | None,
    session_clues: SessionClueState | None,
) -> str:
    if clue_graph is None or session_clues is None or not player_id:
        return ""
    for clue in clue_graph.clues:
        state = session_clues.state_for(clue.id)
        if state not in PLAYER_VISIBLE_STATES:
            continue
        if not clue.visible_to_player(player_id):
            continue
        if info.id != clue.info_id and info.id not in clue.output_info_ids:
            continue
        return (
            "ClueGraph authorization source: "
            f"clue_id={clue.id}; info_id={info.id}; state={state}"
        )
    return ""


def _decision_id(run_mode: RunMode, event_id: str, info_id: str, character_id: str) -> str:
    digest = sha1(f"{run_mode}:{event_id}:{info_id}:{character_id}".encode()).hexdigest()[:10]
    return f"filter_{run_mode}_{digest}"


def _event_info_ids(event: EventRecord) -> list[str]:
    info_ids: list[str] = []
    info_ids.extend(event.required_info_ids)
    info_ids.extend(event.observed_info_ids)
    info_ids.extend(event.known_info_ids)
    info_ids.extend(event.output_info_ids)
    return list(dict.fromkeys(info_ids))


def _relevant_character_ids(
    fixture: KTSLFixture, event: EventRecord, info: InfoLabel
) -> list[str]:
    character_ids = [event.character_id]
    character_ids.extend(info.authorized_character_ids)
    character_ids.extend(info.declassified_for_character_ids)
    character_ids.extend(info.expected_declassified_for_character_ids)
    character_ids.extend(info.known_by_character_ids)
    for state in fixture.initial_knowledge:
        if (
            info.id in state.known_info_ids
            or info.id in state.observed_info_ids
            or info.id in state.authorized_info_ids
        ):
            character_ids.append(state.character_id)
    return [character_id for character_id in dict.fromkeys(character_ids) if character_id]


def _player_id_for_character(
    fixture: KTSLFixture,
    event: EventRecord,
    character_id: str,
    state: ActorKnowledgeState | None,
) -> str:
    if character_id == event.character_id:
        return event.player_id
    if state is not None:
        return state.player_id
    for scene in fixture.scenes:
        if character_id in scene.participant_character_ids:
            index = scene.participant_character_ids.index(character_id)
            if index < len(scene.participant_player_ids):
                return scene.participant_player_ids[index]
    return ""


def _is_authorized(
    info: InfoLabel,
    event: EventRecord,
    character_id: str,
    state: ActorKnowledgeState | None,
) -> bool:
    if character_id in info.authorized_character_ids:
        return True
    if info.kind == "know" and character_id in info.known_by_character_ids:
        return True
    if state is None:
        return False
    return info.id in state.authorized_info_ids or (
        info.kind == "know" and info.id in state.known_info_ids
    )


def _is_declassified(info: InfoLabel, character_id: str, run_mode: RunMode) -> bool:
    if info.is_declassified or character_id in info.declassified_for_character_ids:
        return True
    return run_mode == "ktsl_full" and character_id in info.expected_declassified_for_character_ids


def _has_observed(
    info: InfoLabel,
    event: EventRecord,
    player_id: str,
    state: ActorKnowledgeState | None,
) -> bool:
    if player_id and player_id in info.observed_by_player_ids:
        return True
    if info.id in event.observed_info_ids:
        return True
    return state is not None and info.id in state.observed_info_ids


__all__ = [
    "build_info_lookup",
    "decide_info_access",
    "declassification_completeness",
    "filter_fixture",
]

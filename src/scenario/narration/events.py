"""Deterministic references for committed runtime events."""

from __future__ import annotations

import hashlib
import json

from scenario.runtime.contracts import RuntimeEvent, TurnResolution

from .contracts import NarrationEventRef


def stable_event_hash(event: RuntimeEvent) -> str:
    payload = event.model_dump(mode="json")
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()[:12]


def synthesize_event_id(
    *,
    session_id: str,
    turn_no: int,
    event_index: int,
    event: RuntimeEvent,
) -> str:
    return (
        f"nevt_{session_id}_{turn_no:04d}_{event_index:03d}_"
        f"{event.type}_{stable_event_hash(event)}"
    )


def build_event_refs(resolution: TurnResolution) -> list[NarrationEventRef]:
    refs: list[NarrationEventRef] = []
    for index, event in enumerate(resolution.event_log):
        event_hash = stable_event_hash(event)
        refs.append(
            NarrationEventRef(
                event_id=(
                    f"nevt_{resolution.session_id}_{resolution.turn_no:04d}_"
                    f"{index:03d}_{event.type}_{event_hash}"
                ),
                session_id=resolution.session_id,
                turn_no=resolution.turn_no,
                event_index=index,
                event_type=event.type,
                event_hash=event_hash,
                log_line=event.to_log_line(),
                runtime_event=event,
            )
        )
    return refs


def event_ref_map(event_refs: list[NarrationEventRef]) -> dict[str, NarrationEventRef]:
    return {event_ref.event_id: event_ref for event_ref in event_refs}


def unresolved_event_ids(
    source_event_ids: list[str],
    event_refs: list[NarrationEventRef],
) -> list[str]:
    known_ids = set(event_ref_map(event_refs))
    return [event_id for event_id in source_event_ids if event_id not in known_ids]

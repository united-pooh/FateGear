"""Narration record generation and in-memory persistence."""

from __future__ import annotations

import hashlib
import json

from .contracts import (
    KeeperNarrationRecord,
    ModelMetadata,
    NarrativeState,
    NarrationInputPacket,
    NarrationValidationResult,
    PromptBuildResult,
)


class InMemoryNarrationRepository:
    """Narration-only repository separate from SessionMapState."""

    def __init__(self) -> None:
        self._states: dict[str, NarrativeState] = {}
        self._records: dict[str, list[KeeperNarrationRecord]] = {}

    def get_state(self, session_id: str) -> NarrativeState:
        return self._states.get(session_id, NarrativeState()).model_copy(deep=True)

    def save_state(self, session_id: str, state: NarrativeState) -> None:
        self._states[session_id] = state.model_copy(deep=True)

    def append_record(self, record: KeeperNarrationRecord) -> None:
        self._records.setdefault(record.session_id, []).append(record)

    def list_records(self, session_id: str) -> list[KeeperNarrationRecord]:
        return list(self._records.get(session_id, []))

    def recent_summary(self, session_id: str, *, limit: int = 3) -> str:
        records = self._records.get(session_id, [])[-limit:]
        return "\n".join(record.final_public_text for record in records)


def build_narration_record(
    *,
    packet: NarrationInputPacket,
    validation: NarrationValidationResult,
    prompt: PromptBuildResult,
    model_metadata: ModelMetadata | None = None,
) -> KeeperNarrationRecord:
    model_metadata = model_metadata or ModelMetadata()
    source_event_ids = _ordered_ids(validation.final_draft.source_event_ids)
    cited_memory_ids = _ordered_ids(validation.final_draft.cited_memory_ids)
    replay_input = {
        "packet": packet.model_dump(mode="json"),
        "draft": validation.final_draft.model_dump(mode="json"),
        "model_metadata": model_metadata.model_dump(mode="json"),
    }
    record_id = _record_id(
        {
            "session_id": packet.session_id,
            "turn_no": packet.turn_no,
            "public_text": validation.final_draft.public_text,
            "source_event_ids": source_event_ids,
            "cited_memory_ids": cited_memory_ids,
            "accepted_patches": [
                patch.model_dump(mode="json")
                for patch in validation.accepted_patches
            ],
            "rejected_patches": [
                patch.model_dump(mode="json")
                for patch in validation.rejected_patches
            ],
            "fallback_used": validation.fallback_used,
            "fallback_reasons": validation.fallback_reasons,
            "model_metadata": model_metadata.model_dump(mode="json"),
        }
    )
    return KeeperNarrationRecord(
        record_id=record_id,
        session_id=packet.session_id,
        turn_no=packet.turn_no,
        final_public_text=validation.final_draft.public_text,
        npc_lines=list(validation.final_draft.npc_lines),
        keeper_notes=list(validation.final_draft.keeper_notes),
        accepted_patches=list(validation.accepted_patches),
        rejected_patches=list(validation.rejected_patches),
        source_event_ids=source_event_ids,
        cited_memory_ids=cited_memory_ids,
        model_metadata=model_metadata,
        fallback_used=validation.fallback_used,
        fallback_reasons=list(validation.fallback_reasons),
        validation_warnings=list(validation.warnings),
        prompt_layer_summaries=list(prompt.layers),
        replay_input=replay_input,
        log_summary={
            "prompt_layers": [
                layer.model_dump(mode="json") for layer in prompt.layers
            ],
            "used_event_ids": source_event_ids,
            "used_memory_ids": cited_memory_ids,
            "accepted_patch_paths": [
                patch.path for patch in validation.accepted_patches
            ],
            "rejected_patch_paths": [
                patch.path for patch in validation.rejected_patches
            ],
            "fallback_used": validation.fallback_used,
            "validation_warnings": list(validation.warnings),
        },
    )


def _record_id(payload: object) -> str:
    text = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return f"knr_{hashlib.sha256(text.encode('utf-8')).hexdigest()[:16]}"


def _ordered_ids(ids: list[str]) -> list[str]:
    return list(dict.fromkeys(ids))

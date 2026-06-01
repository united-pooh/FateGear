"""Auxiliary vector-memory contracts and in-memory implementation."""

from __future__ import annotations

import hashlib
from typing import Literal
from typing import Protocol

from .contracts import (
    KeeperNarrationRecord,
    NarrationInputPacket,
    NarrationPatchProposal,
    VectorMemory,
    VectorMemoryMetadata,
)


class VectorContextStore(Protocol):
    def retrieve(
        self,
        packet: NarrationInputPacket,
        *,
        kinds: set[str] | None = None,
        limit: int = 8,
    ) -> list[VectorMemory]:
        """Return non-authoritative context memories for the current packet."""

    def write_from_record(
        self,
        record: KeeperNarrationRecord,
    ) -> list[VectorMemory]:
        """Persist accepted narration output as future auxiliary memory."""


class InMemoryVectorContextStore:
    """Simple deterministic memory store for the first narration version."""

    def __init__(self, memories: list[VectorMemory] | None = None) -> None:
        self._memories: list[VectorMemory] = list(memories or [])

    def add(self, memory: VectorMemory) -> None:
        self._memories.append(memory)

    def all(self) -> list[VectorMemory]:
        return list(self._memories)

    def retrieve(
        self,
        packet: NarrationInputPacket,
        *,
        kinds: set[str] | None = None,
        limit: int = 8,
    ) -> list[VectorMemory]:
        candidates = [
            memory
            for memory in self._memories
            if (kinds is None or memory.metadata.kind in kinds)
            and memory.metadata.scope == "public"
            and not memory_conflicts_with_packet(memory, packet)
        ]
        candidates.sort(
            key=lambda memory: (
                -memory.metadata.confidence,
                -memory.metadata.source_turn,
                memory.memory_id,
            )
        )
        return candidates[:limit]

    def write_from_record(
        self,
        record: KeeperNarrationRecord,
    ) -> list[VectorMemory]:
        memories: list[VectorMemory] = []
        if record.final_public_text:
            memories.append(
                _record_memory(
                    record,
                    kind="narrative",
                    text=record.final_public_text,
                    created_from="record",
                )
            )
        for patch in record.accepted_patches:
            memories.append(_patch_memory(record, patch))
        self._memories.extend(memories)
        return memories


def memory_conflicts_with_packet(
    memory: VectorMemory,
    packet: NarrationInputPacket,
) -> bool:
    text = _normalize(memory.summary_text + " " + memory.metadata.source_text)
    if any(_normalize(fact) and _normalize(fact) in text for fact in packet.forbidden_facts):
        return True
    for check in packet.check_results:
        action_names = [check.action_id, check.action_name]
        if not any(_normalize(name) and _normalize(name) in text for name in action_names):
            continue
        if check.success and _contains_failure_claim(text):
            return True
        if not check.success and _contains_success_claim(text):
            return True
    return False


def _record_memory(
    record: KeeperNarrationRecord,
    *,
    kind: Literal["narrative", "npc", "scene", "clue"],
    text: str,
    created_from: Literal["seed", "record", "patch"],
) -> VectorMemory:
    memory_id = _memory_id(record.record_id, kind, text)
    return VectorMemory(
        metadata=VectorMemoryMetadata(
            memory_id=memory_id,
            source_turn=record.turn_no,
            source_event_ids=list(record.source_event_ids),
            scope="public",
            kind=kind,  # type: ignore[arg-type]
            confidence=1.0,
            source_text=text,
            source_record_id=record.record_id,
            created_from=created_from,
        ),
        summary_text=text,
    )


def _patch_memory(
    record: KeeperNarrationRecord,
    patch: NarrationPatchProposal,
) -> VectorMemory:
    text = f"NarrativeState {patch.path} -> {patch.new_value}"
    return _record_memory(
        record,
        kind=_memory_kind_for_patch(patch),
        text=text,
        created_from="patch",
    )


def _memory_kind_for_patch(
    patch: NarrationPatchProposal,
) -> Literal["narrative", "npc", "scene", "clue"]:
    root = patch.path.split(".", 1)[0]
    if root == "npc_attitudes":
        return "npc"
    if root == "scene_mood" or root == "public_observations":
        return "scene"
    if root == "clue_emphasis":
        return "clue"
    return "narrative"


def _memory_id(record_id: str, kind: str, text: str) -> str:
    digest = hashlib.sha256(f"{record_id}:{kind}:{text}".encode("utf-8")).hexdigest()
    return f"mem_{digest[:16]}"


def _contains_success_claim(text: str) -> bool:
    return any(token in text for token in ("success", "succeeds", "成功", "顺利", "完成"))


def _contains_failure_claim(text: str) -> bool:
    return any(token in text for token in ("failed", "failure", "失败", "未能", "没有"))


def _normalize(value: str) -> str:
    return value.casefold().strip()

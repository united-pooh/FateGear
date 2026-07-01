"""Auxiliary vector-memory contracts and narration memory stores."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from threading import RLock
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
            and memory.metadata.status == "active"
            and _matches_packet_scope(memory, packet)
            and (
                memory.metadata.valid_from_turn is None
                or packet.turn_no >= memory.metadata.valid_from_turn
            )
            and (
                memory.metadata.valid_to_turn is None
                or packet.turn_no < memory.metadata.valid_to_turn
            )
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


class PersistentNarrationMemoryStore:
    """JSONL-backed narration memory store with audit and soft invalidation."""

    def __init__(
        self,
        path: str | Path,
        *,
        memories: list[VectorMemory] | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self.path = Path(path)
        self._clock = clock or (lambda: datetime.now(UTC))
        self._lock = RLock()
        self._load_errors: list[dict[str, object]] = []
        self._last_retrieval_trace: list[dict[str, object]] = []
        self._memories: list[VectorMemory] = self._load()
        if memories:
            with self._lock:
                for memory in memories:
                    self._upsert(memory)
                self._persist()

    def add(self, memory: VectorMemory) -> None:
        with self._lock:
            self._upsert(memory)
            self._persist()

    def all(self, *, include_inactive: bool = False) -> list[VectorMemory]:
        with self._lock:
            if include_inactive:
                return list(self._memories)
            return [
                memory
                for memory in self._memories
                if memory.metadata.status == "active"
            ]

    def retrieve(
        self,
        packet: NarrationInputPacket,
        *,
        kinds: set[str] | None = None,
        limit: int = 8,
    ) -> list[VectorMemory]:
        with self._lock:
            memories = list(self._memories)

        trace: list[dict[str, object]] = []
        candidates: list[VectorMemory] = []
        for memory in memories:
            reason = self._retrieval_filter_reason(memory, packet, kinds=kinds)
            selected = reason == "selected"
            trace.append(
                _retrieval_trace_entry(memory, selected=selected, reason=reason)
            )
            if selected:
                candidates.append(memory)
        candidates.sort(key=_memory_rank)
        results = candidates[:limit]

        selected_rank = {
            memory.memory_id: rank for rank, memory in enumerate(results, start=1)
        }
        for item in trace:
            if item["reason"] != "selected":
                continue
            memory_id = str(item["memory_id"])
            if memory_id in selected_rank:
                item["rank"] = selected_rank[memory_id]
            else:
                item["selected"] = False
                item["reason"] = "rank_limit"

        with self._lock:
            self._last_retrieval_trace = trace
        return results

    def last_retrieval_trace(self) -> list[dict[str, object]]:
        """Return the privacy-safe rejection/selection trace for the last retrieve."""

        with self._lock:
            return [dict(item) for item in self._last_retrieval_trace]

    def search(
        self,
        query: str,
        *,
        kinds: set[str] | None = None,
        session_id: str | None = None,
        module_id: str | None = None,
        include_inactive: bool = False,
        limit: int = 20,
    ) -> list[VectorMemory]:
        needle = _normalize(query)
        with self._lock:
            memories = list(self._memories)
        candidates = [
            memory
            for memory in memories
            if (include_inactive or memory.metadata.status == "active")
            and (kinds is None or memory.metadata.kind in kinds)
            and _matches_search_scope(
                memory,
                session_id=session_id,
                module_id=module_id,
            )
            and (not needle or needle in _search_blob(memory))
        ]
        candidates.sort(key=_memory_rank)
        return candidates[:limit]

    def forget(self, memory_id: str, *, reason: str = "") -> VectorMemory:
        now = self._now()
        with self._lock:
            for index, memory in enumerate(self._memories):
                if memory.memory_id != memory_id:
                    continue
                forgotten = memory.model_copy(
                    update={
                        "metadata": memory.metadata.model_copy(
                            update={
                                "status": "forgotten",
                                "updated_at": now,
                                "forget_reason": reason,
                            }
                        )
                    },
                    deep=True,
                )
                self._memories[index] = forgotten
                self._persist()
                return forgotten
        raise KeyError(f"unknown memory_id: {memory_id}")

    def redact(self, memory_id: str, *, reason: str) -> VectorMemory:
        """Forget a memory while removing persisted source and summary text."""

        now = self._now()
        with self._lock:
            for index, memory in enumerate(self._memories):
                if memory.memory_id != memory_id:
                    continue
                redacted = memory.model_copy(
                    update={
                        "metadata": memory.metadata.model_copy(
                            update={
                                "status": "forgotten",
                                "source_text": "[redacted]",
                                "updated_at": now,
                                "forget_reason": reason,
                            }
                        ),
                        "summary_text": "[redacted]",
                    },
                    deep=True,
                )
                self._memories[index] = redacted
                self._persist()
                return redacted
        raise KeyError(f"unknown memory_id: {memory_id}")

    def write_from_record(
        self,
        record: KeeperNarrationRecord,
    ) -> list[VectorMemory]:
        now = self._now()
        memories: list[VectorMemory] = []
        if record.final_public_text:
            memories.append(
                _record_memory(
                    record,
                    kind="narrative",
                    text=record.final_public_text,
                    created_from="record",
                    timestamp=now,
                )
            )
        for patch in record.accepted_patches:
            memories.append(_patch_memory(record, patch, timestamp=now))
        with self._lock:
            memories = self._supersede_patch_memories(memories, record=record, now=now)
            for memory in memories:
                self._upsert(memory)
            self._persist()
        return memories

    def export_audit(self) -> dict[str, object]:
        with self._lock:
            memories = [
                {
                    "memory_id": memory.memory_id,
                    "status": memory.metadata.status,
                    "kind": memory.metadata.kind,
                    "scope": memory.metadata.scope,
                    "session_id": memory.metadata.session_id,
                    "module_id": memory.metadata.module_id,
                    "source_turn": memory.metadata.source_turn,
                    "source_event_ids": list(memory.metadata.source_event_ids),
                    "source_record_id": memory.metadata.source_record_id,
                    "created_from": memory.metadata.created_from,
                    "created_at": memory.metadata.created_at,
                    "updated_at": memory.metadata.updated_at,
                    "valid_from_turn": memory.metadata.valid_from_turn,
                    "valid_to_turn": memory.metadata.valid_to_turn,
                    "supersedes": list(memory.metadata.supersedes),
                    "tags": list(memory.metadata.tags),
                    "forget_reason": memory.metadata.forget_reason,
                    "summary_text": memory.summary_text,
                }
                for memory in self._memories
            ]
            load_errors = list(self._load_errors)
            last_retrieval_trace = [
                dict(item) for item in self._last_retrieval_trace
            ]
        return {
            "path": str(self.path),
            "active_count": len([item for item in memories if item["status"] == "active"]),
            "total_count": len(memories),
            "load_errors": load_errors,
            "last_retrieval_trace": last_retrieval_trace,
            "memories": memories,
        }

    def _is_retrievable(
        self,
        memory: VectorMemory,
        packet: NarrationInputPacket,
    ) -> bool:
        return self._retrieval_filter_reason(memory, packet, kinds=None) == "selected"

    def _retrieval_filter_reason(
        self,
        memory: VectorMemory,
        packet: NarrationInputPacket,
        *,
        kinds: set[str] | None,
    ) -> str:
        metadata = memory.metadata
        if kinds is not None and metadata.kind not in kinds:
            return "kind_mismatch"
        if metadata.status != "active":
            return f"status:{metadata.status}"
        if metadata.scope != "public":
            return f"scope:{metadata.scope}"
        if not _matches_packet_scope(memory, packet):
            return "scope_mismatch"
        if metadata.valid_from_turn is not None and packet.turn_no < metadata.valid_from_turn:
            return "not_yet_valid"
        if metadata.valid_to_turn is not None and packet.turn_no >= metadata.valid_to_turn:
            return "expired"
        if memory_conflicts_with_packet(memory, packet):
            return "packet_conflict"
        return "selected"

    def _load(self) -> list[VectorMemory]:
        if not self.path.exists():
            return []
        memories: list[VectorMemory] = []
        for line_no, line in enumerate(
            self.path.read_text(encoding="utf-8").splitlines(),
            start=1,
        ):
            if not line.strip():
                continue
            try:
                memories.append(VectorMemory.model_validate_json(line))
            except Exception as exc:  # noqa: BLE001 - bad audit rows should not stop boot.
                self._load_errors.append(
                    {
                        "line_no": line_no,
                        "error": str(exc),
                    }
                )
        return memories

    def _persist(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp_path = self.path.with_suffix(f"{self.path.suffix}.tmp")
        lines = [
            json.dumps(
                memory.model_dump(mode="json"),
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            for memory in self._memories
        ]
        temp_path.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
        temp_path.replace(self.path)

    def _upsert(self, memory: VectorMemory) -> None:
        for index, existing in enumerate(self._memories):
            if existing.memory_id == memory.memory_id:
                self._memories[index] = memory
                return
        self._memories.append(memory)

    def _supersede_patch_memories(
        self,
        memories: list[VectorMemory],
        *,
        record: KeeperNarrationRecord,
        now: str,
    ) -> list[VectorMemory]:
        updated_memories: list[VectorMemory] = []
        for memory in memories:
            patch_path = _patch_path(memory)
            if memory.metadata.created_from != "patch" or patch_path is None:
                updated_memories.append(memory)
                continue
            superseded_ids: list[str] = []
            for index, existing in enumerate(self._memories):
                if (
                    existing.metadata.status != "active"
                    or existing.metadata.created_from != "patch"
                    or _patch_path(existing) != patch_path
                    or existing.metadata.session_id != memory.metadata.session_id
                    or existing.metadata.module_id != memory.metadata.module_id
                    or existing.memory_id == memory.memory_id
                ):
                    continue
                superseded_ids.append(existing.memory_id)
                self._memories[index] = existing.model_copy(
                    update={
                        "metadata": existing.metadata.model_copy(
                            update={
                                "status": "stale",
                                "updated_at": now,
                                "valid_to_turn": record.turn_no,
                            }
                        )
                    },
                    deep=True,
                )
            updated_memories.append(
                memory.model_copy(
                    update={
                        "metadata": memory.metadata.model_copy(
                            update={
                                "supersedes": list(
                                    dict.fromkeys(
                                        [
                                            *memory.metadata.supersedes,
                                            *superseded_ids,
                                        ]
                                    )
                                )
                            }
                        )
                    },
                    deep=True,
                )
            )
        return updated_memories

    def _now(self) -> str:
        return self._clock().astimezone(UTC).isoformat()


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
    source_event_ids: list[str] | None = None,
    timestamp: str = "",
) -> VectorMemory:
    memory_id = _memory_id(record.record_id, kind, text)
    source_event_ids = (
        list(dict.fromkeys(source_event_ids))
        if source_event_ids is not None
        else list(record.source_event_ids)
    )
    return VectorMemory(
        metadata=VectorMemoryMetadata(
            memory_id=memory_id,
            source_turn=record.turn_no,
            source_event_ids=source_event_ids,
            session_id=record.session_id,
            module_id=_record_module_id(record),
            scope="public",
            kind=kind,  # type: ignore[arg-type]
            confidence=1.0,
            source_text=text,
            source_record_id=record.record_id,
            created_from=created_from,
            created_at=timestamp,
            updated_at=timestamp,
            valid_from_turn=record.turn_no,
        ),
        summary_text=text,
    )


def _patch_memory(
    record: KeeperNarrationRecord,
    patch: NarrationPatchProposal,
    *,
    timestamp: str = "",
) -> VectorMemory:
    text = f"NarrativeState {patch.path} -> {patch.new_value}"
    source_event_ids = list(dict.fromkeys(patch.source_event_ids or record.source_event_ids))
    memory = _record_memory(
        record,
        kind=_memory_kind_for_patch(patch),
        text=text,
        created_from="patch",
        source_event_ids=source_event_ids,
        timestamp=timestamp,
    )
    return memory.model_copy(
        update={
            "metadata": memory.metadata.model_copy(
                update={"tags": [*_without_patch_tags(memory.metadata.tags), f"path:{patch.path}"]}
            )
        },
        deep=True,
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


def _record_module_id(record: KeeperNarrationRecord) -> str:
    packet = record.replay_input.get("packet") if isinstance(record.replay_input, dict) else None
    if isinstance(packet, dict):
        module_id = packet.get("module_id")
        return str(module_id) if module_id is not None else ""
    return ""


def _memory_rank(memory: VectorMemory) -> tuple[float, int, str]:
    return (
        -memory.metadata.confidence,
        -memory.metadata.source_turn,
        memory.memory_id,
    )


def _retrieval_trace_entry(
    memory: VectorMemory,
    *,
    selected: bool,
    reason: str,
) -> dict[str, object]:
    metadata = memory.metadata
    return {
        "memory_id": memory.memory_id,
        "selected": selected,
        "reason": reason,
        "status": metadata.status,
        "kind": metadata.kind,
        "scope": metadata.scope,
        "session_id": metadata.session_id,
        "module_id": metadata.module_id,
        "source_turn": metadata.source_turn,
        "source_record_id": metadata.source_record_id,
        "created_from": metadata.created_from,
        "valid_from_turn": metadata.valid_from_turn,
        "valid_to_turn": metadata.valid_to_turn,
    }


def _search_blob(memory: VectorMemory) -> str:
    metadata = memory.metadata
    return _normalize(
        " ".join(
            [
                memory.memory_id,
                metadata.kind,
                metadata.scope,
                metadata.status,
                metadata.session_id,
                metadata.module_id,
                metadata.source_record_id,
                metadata.source_text,
                memory.summary_text,
                *metadata.tags,
            ]
        )
    )


def _matches_packet_scope(memory: VectorMemory, packet: NarrationInputPacket) -> bool:
    metadata = memory.metadata
    if _is_global_seed(memory):
        return True
    return metadata.session_id == packet.session_id and metadata.module_id == packet.module_id


def _matches_search_scope(
    memory: VectorMemory,
    *,
    session_id: str | None,
    module_id: str | None,
) -> bool:
    metadata = memory.metadata
    if _is_global_seed(memory):
        return True
    if session_id is None or module_id is None:
        return False
    if session_id is not None and metadata.session_id != session_id:
        return False
    if module_id is not None and metadata.module_id != module_id:
        return False
    return True


def _is_global_seed(memory: VectorMemory) -> bool:
    metadata = memory.metadata
    return (
        metadata.created_from == "seed"
        and metadata.session_id == ""
        and metadata.module_id == ""
    )


def _patch_path(memory: VectorMemory) -> str | None:
    prefix = "path:"
    for tag in memory.metadata.tags:
        if tag.startswith(prefix) and len(tag) > len(prefix):
            return tag[len(prefix):]
    return None


def _without_patch_tags(tags: list[str]) -> list[str]:
    return [tag for tag in tags if not tag.startswith("path:")]


def _contains_success_claim(text: str) -> bool:
    return any(token in text for token in ("success", "succeeds", "成功", "顺利", "完成"))


def _contains_failure_claim(text: str) -> bool:
    return any(token in text for token in ("failed", "failure", "失败", "未能", "没有"))


def _normalize(value: str) -> str:
    return value.casefold().strip()

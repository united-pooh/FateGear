from __future__ import annotations

import json

from scenario.narration import (
    KeeperNarrationRecord,
    NarrationInputPacket,
    NarrationPatchProposal,
    PersistentNarrationMemoryStore,
    VectorMemory,
    VectorMemoryMetadata,
    build_narration_input_packet,
)
from scenario.runtime import RuntimeEvent, TurnResolution
from scenario.runtime.engine import SceneRuntime

from tests.scene.card_fixtures import build_player_cards


def test_retrieve_isolates_session_module_and_allows_global_seed(tmp_path) -> None:
    store = PersistentNarrationMemoryStore(tmp_path / "narration-memory.jsonl")
    packet = _packet(session_id="session-a", turn_no=2)
    global_seed = _global_seed()
    store.add(global_seed)
    written = store.write_from_record(_record_with_scene_patch(packet=packet))

    same_scope = store.retrieve(packet)
    other_session = store.retrieve(packet.model_copy(update={"session_id": "session-b"}))
    other_module = store.retrieve(packet.model_copy(update={"module_id": "other-module"}))

    assert {memory.memory_id for memory in same_scope} == {
        global_seed.memory_id,
        *[memory.memory_id for memory in written],
    }
    assert [memory.memory_id for memory in other_session] == [global_seed.memory_id]
    assert [memory.memory_id for memory in other_module] == [global_seed.memory_id]


def test_retrieve_records_privacy_safe_trace_with_rejection_reasons(tmp_path) -> None:
    store = PersistentNarrationMemoryStore(tmp_path / "narration-memory.jsonl")
    packet = _packet(session_id="session-a", turn_no=2)
    store.add(_global_seed(memory_id="seed-trace"))
    store.write_from_record(_record_with_scene_patch(packet=packet))
    store.add(
        _scoped_memory(
            memory_id="other-session",
            session_id="session-b",
            module_id=packet.module_id,
            summary_text="另一局门厅里不该泄漏的煤油灯。",
        )
    )
    store.add(
        _scoped_memory(
            memory_id="stale-note",
            session_id=packet.session_id,
            module_id=packet.module_id,
            status="stale",
            summary_text="已经过期的门厅气味。",
        )
    )

    result = store.retrieve(packet, limit=2)
    trace = store.last_retrieval_trace()
    by_id = {item["memory_id"]: item for item in trace}

    assert len(result) == 2
    assert by_id["other-session"]["reason"] == "scope_mismatch"
    assert by_id["stale-note"]["reason"] == "status:stale"
    assert by_id["seed-trace"]["reason"] == "rank_limit"
    assert by_id["seed-trace"]["selected"] is False
    assert all("summary_text" not in item for item in trace)
    assert all("source_text" not in item for item in trace)
    assert store.export_audit()["last_retrieval_trace"] == trace


def test_search_defaults_to_global_seed_and_filters_scoped_records(tmp_path) -> None:
    store = PersistentNarrationMemoryStore(tmp_path / "narration-memory.jsonl")
    packet = _packet(session_id="session-a")
    store.add(_global_seed(summary_text="全局种子：雨夜叙事保持克制。"))
    written = store.write_from_record(_record_with_scene_patch(packet=packet))
    scoped_record = next(memory for memory in written if "煤油灯" in memory.summary_text)

    assert store.search("煤油灯") == []
    assert [memory.memory_id for memory in store.search("全局种子")] == ["seed-global"]
    assert store.search("煤油灯", session_id=packet.session_id) == []
    assert store.search("煤油灯", module_id=packet.module_id) == []
    assert [
        memory.memory_id
        for memory in store.search(
            "煤油灯",
            session_id=packet.session_id,
            module_id=packet.module_id,
        )
    ] == [scoped_record.memory_id]


def test_patch_memory_preserves_patch_event_ids_and_falls_back_to_record_ids(
    tmp_path,
) -> None:
    store = PersistentNarrationMemoryStore(tmp_path / "narration-memory.jsonl")
    packet = _packet(session_id="session-a")
    record = _record_with_scene_patch(
        packet=packet,
        record_id="knr-events",
        record_source_event_ids=["record-event"],
        patch_source_event_ids=["patch-event"],
        extra_patches=[
            NarrationPatchProposal(
                path="npc_attitudes.attendant",
                old_value=None,
                new_value="警觉",
                reason="NPC reacted.",
                source_event_ids=[],
            )
        ],
    )

    written = store.write_from_record(record)

    scene_patch = next(
        memory for memory in written if "scene_mood.foyer" in memory.summary_text
    )
    npc_patch = next(
        memory for memory in written if "npc_attitudes.attendant" in memory.summary_text
    )
    assert scene_patch.metadata.source_event_ids == ["patch-event"]
    assert npc_patch.metadata.source_event_ids == ["record-event"]


def test_patch_memory_supersedes_previous_active_path_memory(tmp_path) -> None:
    store = PersistentNarrationMemoryStore(tmp_path / "narration-memory.jsonl")
    packet = _packet(session_id="session-a", turn_no=1)
    first = store.write_from_record(
        _record_with_scene_patch(
            packet=packet,
            record_id="knr-turn-1",
            turn_no=1,
            mood="潮湿",
        )
    )
    second = store.write_from_record(
        _record_with_scene_patch(
            packet=packet.model_copy(update={"turn_no": 3}),
            record_id="knr-turn-3",
            turn_no=3,
            mood="警觉",
        )
    )
    old_patch = next(memory for memory in first if memory.metadata.created_from == "patch")
    new_patch = next(memory for memory in second if memory.metadata.created_from == "patch")

    all_patches = [
        memory
        for memory in store.all(include_inactive=True)
        if memory.metadata.created_from == "patch"
    ]
    retrieved_patch_ids = {
        memory.memory_id
        for memory in store.retrieve(packet.model_copy(update={"turn_no": 4}))
        if memory.metadata.created_from == "patch"
    }

    stale = next(memory for memory in all_patches if memory.memory_id == old_patch.memory_id)
    active = next(memory for memory in all_patches if memory.memory_id == new_patch.memory_id)
    assert stale.metadata.status == "stale"
    assert stale.metadata.valid_to_turn == 3
    assert active.metadata.status == "active"
    assert active.metadata.supersedes == [old_patch.memory_id]
    assert retrieved_patch_ids == {new_patch.memory_id}


def test_retrieve_uses_half_open_validity_window(tmp_path) -> None:
    store = PersistentNarrationMemoryStore(tmp_path / "narration-memory.jsonl")
    memory = _global_seed(
        memory_id="seed-window",
        summary_text="只在第二回合前可用的全局种子。",
    ).model_copy(
        update={
            "metadata": _global_seed().metadata.model_copy(
                update={
                    "memory_id": "seed-window",
                    "source_text": "只在第二回合前可用的全局种子。",
                    "valid_from_turn": 1,
                    "valid_to_turn": 2,
                }
            )
        },
        deep=True,
    )
    store.add(memory)

    assert [item.memory_id for item in store.retrieve(_packet(turn_no=1))] == [
        "seed-window"
    ]
    assert store.retrieve(_packet(turn_no=2)) == []


def test_redact_replaces_text_marks_forgotten_and_audits_reason(tmp_path) -> None:
    store = PersistentNarrationMemoryStore(tmp_path / "narration-memory.jsonl")
    packet = _packet(session_id="session-a")
    written = store.write_from_record(_record_with_scene_patch(packet=packet))
    target = next(memory for memory in written if "煤油灯" in memory.summary_text)

    redacted = store.redact(target.memory_id, reason="user privacy request")

    assert redacted.metadata.status == "forgotten"
    assert redacted.metadata.source_text == "[redacted]"
    assert redacted.summary_text == "[redacted]"
    assert redacted.metadata.forget_reason == "user privacy request"
    assert (
        store.search(
            "煤油灯",
            session_id=packet.session_id,
            module_id=packet.module_id,
            include_inactive=True,
        )
        == []
    )
    audit_memory = next(
        item
        for item in store.export_audit()["memories"]
        if item["memory_id"] == target.memory_id
    )
    assert audit_memory["status"] == "forgotten"
    assert audit_memory["summary_text"] == "[redacted]"
    assert audit_memory["forget_reason"] == "user privacy request"


def test_bad_jsonl_lines_are_skipped_and_reported_in_audit(tmp_path) -> None:
    path = tmp_path / "narration-memory.jsonl"
    good = _global_seed(memory_id="seed-good", summary_text="全局种子一")
    also_good = _global_seed(memory_id="seed-also-good", summary_text="全局种子二")
    path.write_text(
        "\n".join(
            [
                _json_line(good),
                "{not-json",
                _json_line(also_good),
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    store = PersistentNarrationMemoryStore(path)
    audit = store.export_audit()

    assert {memory.memory_id for memory in store.all()} == {
        "seed-good",
        "seed-also-good",
    }
    assert audit["active_count"] == 2
    assert audit["total_count"] == 2
    assert audit["load_errors"][0]["line_no"] == 2
    assert "Invalid JSON" in audit["load_errors"][0]["error"]


def _record_with_scene_patch(
    *,
    packet: NarrationInputPacket,
    record_id: str = "knr-persist",
    turn_no: int | None = None,
    mood: str = "潮湿而紧张",
    record_source_event_ids: list[str] | None = None,
    patch_source_event_ids: list[str] | None = None,
    extra_patches: list[NarrationPatchProposal] | None = None,
) -> KeeperNarrationRecord:
    turn_no = turn_no or packet.turn_no
    event_ids = [packet.event_refs[0].event_id]
    record_event_ids = record_source_event_ids if record_source_event_ids is not None else event_ids
    patch_event_ids = patch_source_event_ids if patch_source_event_ids is not None else event_ids
    patches = [
        NarrationPatchProposal(
            path="scene_mood.foyer",
            old_value=None,
            new_value=mood,
            reason="The foyer mood changed.",
            source_event_ids=patch_event_ids,
        )
    ]
    patches.extend(extra_patches or [])
    return KeeperNarrationRecord(
        record_id=record_id,
        session_id=packet.session_id,
        turn_no=turn_no,
        final_public_text="门厅里有雨水和煤油灯的气味。",
        source_event_ids=record_event_ids,
        accepted_patches=patches,
        replay_input={"packet": packet.model_dump(mode="json")},
    )


def _packet(
    *,
    session_id: str = "session-a",
    module_id: str = "generic_mvp",
    turn_no: int = 1,
) -> NarrationInputPacket:
    runtime = SceneRuntime(roll_provider=lambda: 1)
    session = runtime.create_session(
        "generic_mvp",
        ["p1"],
        player_cards=build_player_cards(["p1"]),
    )
    packet = build_narration_input_packet(
        resolution=TurnResolution(
            session_id=session.session_id,
            turn_no=turn_no,
            next_turn=turn_no + 1,
            event_log=[
                RuntimeEvent(type="turn_started", turn_no=turn_no, message="开始"),
            ],
        ),
        session=session,
        module=runtime._load_module("generic_mvp"),  # noqa: SLF001
    )
    return packet.model_copy(update={"session_id": session_id, "module_id": module_id})


def _global_seed(
    *,
    memory_id: str = "seed-global",
    summary_text: str = "全局种子：雨夜叙事保持克制。",
) -> VectorMemory:
    return VectorMemory(
        metadata=VectorMemoryMetadata(
            memory_id=memory_id,
            source_turn=1,
            kind="narrative",
            confidence=0.1,
            source_text=summary_text,
            created_from="seed",
        ),
        summary_text=summary_text,
    )


def _scoped_memory(
    *,
    memory_id: str,
    session_id: str,
    module_id: str,
    summary_text: str,
    status: str = "active",
) -> VectorMemory:
    return VectorMemory(
        metadata=VectorMemoryMetadata(
            memory_id=memory_id,
            source_turn=1,
            source_event_ids=["evt-scoped"],
            session_id=session_id,
            module_id=module_id,
            kind="narrative",
            confidence=0.5,
            source_text=summary_text,
            source_record_id=f"record-{memory_id}",
            created_from="record",
            status=status,  # type: ignore[arg-type]
            valid_from_turn=1,
        ),
        summary_text=summary_text,
    )


def _json_line(memory: VectorMemory) -> str:
    return json.dumps(
        memory.model_dump(mode="json"),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )

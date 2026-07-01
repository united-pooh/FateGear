from __future__ import annotations

from scenario.narration import (
    InMemoryVectorContextStore,
    KeeperNarrationRecord,
    NarrationPatchProposal,
    VectorMemory,
    VectorMemoryMetadata,
    build_narration_input_packet,
)
from scenario.runtime import RuntimeEvent, TurnResolution
from scenario.runtime.engine import SceneRuntime

from tests.scene.card_fixtures import build_player_cards, resolve_turn_sync


def _packet_with_failed_check():
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
        forbidden_facts=["hidden-basement"],
    )


def test_in_memory_retrieval_filters_conflicts_and_categories() -> None:
    packet = _packet_with_failed_check()
    ok = VectorMemory(
        metadata=VectorMemoryMetadata(
            memory_id="m-ok",
            source_turn=1,
            kind="scene",
            confidence=0.9,
        ),
        summary_text="储藏室保持潮湿和压抑。",
    )
    conflict = VectorMemory(
        metadata=VectorMemoryMetadata(
            memory_id="m-conflict",
            source_turn=1,
            kind="narrative",
            confidence=1.0,
        ),
        summary_text="搜索钥匙成功完成，并发现 hidden-basement。",
    )
    store = InMemoryVectorContextStore([ok, conflict])

    assert store.retrieve(packet, kinds={"scene", "narrative"}) == [ok]
    assert store.retrieve(packet, kinds={"npc"}) == []


def test_in_memory_retrieval_isolates_scope_and_allows_global_seed() -> None:
    packet = _packet_with_failed_check()
    same_scope = VectorMemory(
        metadata=VectorMemoryMetadata(
            memory_id="m-same",
            source_turn=1,
            session_id=packet.session_id,
            module_id=packet.module_id,
            kind="scene",
            confidence=0.9,
            source_text="同一团的门厅记忆。",
            created_from="record",
        ),
        summary_text="同一团的门厅记忆。",
    )
    other_scope = same_scope.model_copy(
        update={
            "metadata": same_scope.metadata.model_copy(
                update={
                    "memory_id": "m-other",
                    "session_id": "other-session",
                    "source_text": "别的团的门厅记忆。",
                }
            ),
            "summary_text": "别的团的门厅记忆。",
        },
        deep=True,
    )
    global_seed = VectorMemory(
        metadata=VectorMemoryMetadata(
            memory_id="m-seed",
            source_turn=1,
            kind="scene",
            confidence=0.1,
            source_text="全局叙事风格种子。",
            created_from="seed",
        ),
        summary_text="全局叙事风格种子。",
    )
    stale = same_scope.model_copy(
        update={
            "metadata": same_scope.metadata.model_copy(
                update={"memory_id": "m-stale", "status": "stale"}
            ),
            "summary_text": "已经过期的同团记忆。",
        },
        deep=True,
    )
    expired = same_scope.model_copy(
        update={
            "metadata": same_scope.metadata.model_copy(
                update={"memory_id": "m-expired", "valid_to_turn": packet.turn_no}
            ),
            "summary_text": "边界回合已经失效的同团记忆。",
        },
        deep=True,
    )
    store = InMemoryVectorContextStore(
        [other_scope, same_scope, global_seed, stale, expired]
    )

    assert [memory.memory_id for memory in store.retrieve(packet)] == [
        "m-same",
        "m-seed",
    ]


def test_writeback_records_accepted_output_and_excludes_rejected_patch_text() -> None:
    event = RuntimeEvent(type="turn_started", turn_no=1, message="开始")
    resolution = TurnResolution(session_id="s1", turn_no=1, next_turn=2, event_log=[event])
    event_id = build_narration_input_packet(
        resolution=resolution,
        session=SceneRuntime(roll_provider=lambda: 1).create_session(
            "generic_mvp",
            ["p1"],
            player_cards=build_player_cards(["p1"]),
        ),
        module=SceneRuntime()._load_module("generic_mvp"),  # noqa: SLF001
    ).event_refs[0].event_id
    accepted = NarrationPatchProposal(
        path="scene_mood.foyer",
        old_value=None,
        new_value="calm",
        reason="accepted",
        source_event_ids=[event_id],
    )
    rejected = accepted.model_copy(update={"new_value": "do-not-store"})
    record = KeeperNarrationRecord(
        record_id="knr-memory",
        session_id="s1",
        turn_no=1,
        final_public_text="安全的公开叙事。",
        accepted_patches=[accepted],
        rejected_patches=[],
        source_event_ids=[event_id],
    )
    record.rejected_patches = []
    store = InMemoryVectorContextStore()

    written = store.write_from_record(record)

    assert len(written) == 2
    assert any("安全的公开叙事" in memory.summary_text for memory in written)
    assert any("calm" in memory.summary_text for memory in written)
    assert all(rejected.new_value not in memory.summary_text for memory in written)


def test_writeback_routes_patch_memory_by_narrative_field() -> None:
    event = RuntimeEvent(type="turn_started", turn_no=1, message="开始")
    resolution = TurnResolution(session_id="s1", turn_no=1, next_turn=2, event_log=[event])
    runtime = SceneRuntime(roll_provider=lambda: 1)
    session = runtime.create_session(
        "generic_mvp",
        ["p1"],
        player_cards=build_player_cards(["p1"]),
    )
    event_id = build_narration_input_packet(
        resolution=resolution,
        session=session,
        module=runtime._load_module("generic_mvp"),  # noqa: SLF001
    ).event_refs[0].event_id
    record = KeeperNarrationRecord(
        record_id="knr-kinds",
        session_id="s1",
        turn_no=1,
        final_public_text="公开叙事。",
        source_event_ids=[event_id],
        accepted_patches=[
            NarrationPatchProposal(
                path="npc_attitudes.attendant",
                old_value=None,
                new_value="警觉",
                reason="NPC reacted",
                source_event_ids=[event_id],
            ),
            NarrationPatchProposal(
                path="scene_mood.storage",
                old_value=None,
                new_value="压抑",
                reason="Scene became tense",
                source_event_ids=[event_id],
            ),
            NarrationPatchProposal(
                path="clue_emphasis.key",
                old_value=None,
                new_value="钥匙线索被强调",
                reason="Clue surfaced",
                source_event_ids=[event_id],
            ),
        ],
    )

    written = InMemoryVectorContextStore().write_from_record(record)

    assert {memory.metadata.kind for memory in written} == {
        "narrative",
        "npc",
        "scene",
        "clue",
    }

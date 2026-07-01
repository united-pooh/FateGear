from __future__ import annotations

from scenario.narration import (
    InMemoryNarrationRepository,
    InMemoryVectorContextStore,
    KeeperNarrationDraft,
    NarrationPatchProposal,
    NarrationPipeline,
    PersistentNarrationMemoryStore,
    SQLiteNarrationGraphMemory,
    StaticKeeperRenderAgent,
    VectorMemory,
    VectorMemoryMetadata,
    build_event_refs,
)
from scenario.runtime import SceneRuntime

from tests.scene.card_fixtures import build_player_cards, resolve_turn_sync


def test_pipeline_runs_after_resolve_and_mutates_only_narrative_state(tmp_path) -> None:
    runtime = SceneRuntime(roll_provider=lambda: 1)
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
    resolution = resolve_turn_sync(runtime, session.session_id)
    session_before = session.model_dump(mode="json")
    repository = InMemoryNarrationRepository()
    memory_store = InMemoryVectorContextStore()

    event_id = build_event_refs(resolution)[0].event_id
    patch = NarrationPatchProposal(
        path="scene_mood.storage",
        old_value=None,
        new_value="潮湿",
        reason="Movement into storage sets public mood.",
        source_event_ids=[event_id],
    )
    with SQLiteNarrationGraphMemory(tmp_path / "narration-graph.sqlite3") as graph_store:
        pipeline = NarrationPipeline(
            agent=StaticKeeperRenderAgent(
                KeeperNarrationDraft(
                    public_text="玩家进入储藏室。",
                    patch_proposals=[patch],
                    source_event_ids=[event_id],
                )
            ),
            repository=repository,
            memory_store=memory_store,
            graph_store=graph_store,
        )
        record = runtime.render_narration_after_turn(resolution, pipeline)
        graph_facts = graph_store.facts_for_entity(
            "path:scene_mood.storage",
            session_id=session.session_id,
            module_id="generic_mvp",
        )

    assert session.model_dump(mode="json") == session_before
    assert record.final_public_text == "玩家进入储藏室。"
    assert record.accepted_patches == [patch]
    assert repository.get_state(session.session_id).scene_mood["storage"] == "潮湿"
    assert repository.list_records(session.session_id) == [record]
    assert any(memory.metadata.source_record_id == record.record_id for memory in memory_store.all())
    assert [fact["value"] for fact in graph_facts] == ["潮湿"]


def test_pipeline_with_persistent_memory_records_retrieval_trace(tmp_path) -> None:
    runtime = SceneRuntime(roll_provider=lambda: 1)
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
    resolution = resolve_turn_sync(runtime, session.session_id)
    event_id = build_event_refs(resolution)[0].event_id
    repository = InMemoryNarrationRepository()
    memory_store = PersistentNarrationMemoryStore(tmp_path / "narration-memory.jsonl")
    memory_store.add(
        _memory(
            memory_id="pipe-same-scope",
            session_id=session.session_id,
            module_id="generic_mvp",
            summary_text="储藏室先前有淡淡煤油灯烟味。",
        )
    )
    memory_store.add(
        _memory(
            memory_id="pipe-other-scope",
            session_id="other-session",
            module_id="generic_mvp",
            summary_text="另一局的储藏室秘密不能泄漏。",
        )
    )
    memory_store.add(
        _memory(
            memory_id="pipe-global-seed",
            session_id="",
            module_id="",
            summary_text="全局种子：雨夜叙事保持克制。",
            created_from="seed",
            confidence=0.1,
        )
    )

    pipeline = NarrationPipeline(
        agent=StaticKeeperRenderAgent(
            KeeperNarrationDraft(
                public_text="玩家进入储藏室，空气沉下来。",
                source_event_ids=[event_id],
                cited_memory_ids=["pipe-same-scope"],
            )
        ),
        repository=repository,
        memory_store=memory_store,
    )
    record = runtime.render_narration_after_turn(resolution, pipeline)
    trace = memory_store.last_retrieval_trace()
    by_id = {item["memory_id"]: item for item in trace}
    retrieved_memory_ids = record.replay_input["packet"]["retrieved_memory_ids"]
    reloaded = PersistentNarrationMemoryStore(tmp_path / "narration-memory.jsonl")

    assert record.fallback_used is False
    assert record.cited_memory_ids == ["pipe-same-scope"]
    assert "pipe-same-scope" in retrieved_memory_ids
    assert "pipe-global-seed" in retrieved_memory_ids
    assert "pipe-other-scope" not in retrieved_memory_ids
    assert by_id["pipe-same-scope"]["selected"] is True
    assert by_id["pipe-global-seed"]["selected"] is True
    assert by_id["pipe-other-scope"]["reason"] == "scope_mismatch"
    assert any(memory.metadata.source_record_id == record.record_id for memory in reloaded.all())


def _memory(
    *,
    memory_id: str,
    session_id: str,
    module_id: str,
    summary_text: str,
    created_from: str = "record",
    confidence: float = 0.8,
) -> VectorMemory:
    return VectorMemory(
        metadata=VectorMemoryMetadata(
            memory_id=memory_id,
            source_turn=1,
            source_event_ids=["evt-memory"],
            session_id=session_id,
            module_id=module_id,
            kind="narrative",
            confidence=confidence,
            source_text=summary_text,
            source_record_id=f"record-{memory_id}",
            created_from=created_from,  # type: ignore[arg-type]
            valid_from_turn=1,
        ),
        summary_text=summary_text,
    )

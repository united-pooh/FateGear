from __future__ import annotations

from scenario.narration import (
    InMemoryNarrationRepository,
    InMemoryVectorContextStore,
    KeeperNarrationDraft,
    NarrationPatchProposal,
    NarrationPipeline,
    StaticKeeperRenderAgent,
    build_event_refs,
)
from scenario.runtime import SceneRuntime

from tests.scene.card_fixtures import build_player_cards, resolve_turn_sync


def test_pipeline_runs_after_resolve_and_mutates_only_narrative_state() -> None:
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
    )

    record = runtime.render_narration_after_turn(resolution, pipeline)

    assert session.model_dump(mode="json") == session_before
    assert record.final_public_text == "玩家进入储藏室。"
    assert record.accepted_patches == [patch]
    assert repository.get_state(session.session_id).scene_mood["storage"] == "潮湿"
    assert repository.list_records(session.session_id) == [record]
    assert any(memory.metadata.source_record_id == record.record_id for memory in memory_store.all())

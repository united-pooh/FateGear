from __future__ import annotations

import pytest

from scenario.narration import (
    KeeperNarrationRecord,
    NarrationPatchProposal,
    SQLiteNarrationGraphMemory,
)


def _record(
    *,
    record_id: str,
    turn_no: int,
    mood: str,
    session_id: str = "s1",
    module_id: str = "generic_mvp",
    path: str = "scene_mood.foyer",
    source_event_ids: list[str] | None = None,
    cited_memory_ids: list[str] | None = None,
) -> KeeperNarrationRecord:
    patch_source_event_ids = source_event_ids or [f"patch-event-{turn_no}"]
    return KeeperNarrationRecord(
        record_id=record_id,
        session_id=session_id,
        turn_no=turn_no,
        final_public_text=f"门厅变得{mood}。",
        source_event_ids=[f"record-event-{turn_no}"],
        cited_memory_ids=cited_memory_ids or [],
        replay_input={"packet": {"module_id": module_id}},
        accepted_patches=[
            NarrationPatchProposal(
                path=path,
                old_value=None,
                new_value=mood,
                reason="Mood changed.",
                source_event_ids=patch_source_event_ids,
            )
        ],
    )


def test_graph_memory_ingests_scoped_patch_fact_and_memory_citation_edges(
    tmp_path,
) -> None:
    graph = SQLiteNarrationGraphMemory(tmp_path / "narration-graph.sqlite3")

    facts = graph.ingest_record(
        _record(
            record_id="knr-graph-1",
            turn_no=1,
            mood="潮湿",
            source_event_ids=["patch-event-1", "patch-event-1", "patch-event-2"],
            cited_memory_ids=["m1"],
        )
    )

    assert len(facts) == 1
    assert facts[0]["session_id"] == "s1"
    assert facts[0]["module_id"] == "generic_mvp"
    assert facts[0]["entity_id"] == "path:scene_mood.foyer"
    assert facts[0]["relation"] == "narrative_state"
    assert facts[0]["value"] == "潮湿"
    assert facts[0]["valid_from_turn"] == 1
    assert facts[0]["valid_to_turn"] is None
    assert facts[0]["status"] == "active"
    assert facts[0]["source_event_ids"] == ["patch-event-1", "patch-event-2"]

    audit = graph.export_audit()
    assert audit["schema_version"] == "2"
    assert {(entity["session_id"], entity["module_id"], entity["entity_id"]) for entity in audit["entities"]} == {
        ("s1", "generic_mvp", "memory:m1"),
        ("s1", "generic_mvp", "path:scene_mood.foyer"),
    }
    assert audit["facts"][0]["session_id"] == "s1"
    assert audit["facts"][0]["module_id"] == "generic_mvp"
    assert audit["facts"][0]["status"] == "active"
    assert audit["facts"][0]["valid_from_turn"] == 1
    assert audit["facts"][0]["valid_to_turn"] is None
    assert audit["edges"][0]["session_id"] == "s1"
    assert audit["edges"][0]["module_id"] == "generic_mvp"
    assert audit["edges"][0]["relation"] == "cites_memory"
    assert audit["edges"][0]["target_entity_id"] == "memory:m1"


def test_graph_memory_supersedes_only_within_same_session_and_module(tmp_path) -> None:
    graph = SQLiteNarrationGraphMemory(tmp_path / "narration-graph.sqlite3")

    graph.ingest_record(_record(record_id="s1-r1", session_id="s1", turn_no=1, mood="潮湿"))
    graph.ingest_record(_record(record_id="s2-r1", session_id="s2", turn_no=2, mood="温暖"))
    graph.ingest_record(
        _record(
            record_id="s1-other-module-r1",
            session_id="s1",
            module_id="other_module",
            turn_no=2,
            mood="空旷",
        )
    )
    graph.ingest_record(_record(record_id="s1-r2", session_id="s1", turn_no=3, mood="警觉"))

    s1_active = graph.facts_for_entity(
        "path:scene_mood.foyer",
        session_id="s1",
        module_id="generic_mvp",
    )
    s2_active = graph.facts_for_entity(
        "path:scene_mood.foyer",
        session_id="s2",
        module_id="generic_mvp",
    )
    other_module_active = graph.facts_for_entity(
        "path:scene_mood.foyer",
        session_id="s1",
        module_id="other_module",
    )
    s1_all = graph.facts_for_entity(
        "path:scene_mood.foyer",
        session_id="s1",
        module_id="generic_mvp",
        include_inactive=True,
    )

    assert [fact["value"] for fact in s1_active] == ["警觉"]
    assert [fact["value"] for fact in s2_active] == ["温暖"]
    assert [fact["value"] for fact in other_module_active] == ["空旷"]
    assert {fact["status"] for fact in s1_all} == {"active", "superseded"}
    superseded = next(fact for fact in s1_all if fact["status"] == "superseded")
    assert superseded["value"] == "潮湿"
    assert superseded["valid_to_turn"] == 3


def test_graph_memory_as_of_turn_uses_half_open_validity(tmp_path) -> None:
    graph = SQLiteNarrationGraphMemory(tmp_path / "narration-graph.sqlite3")
    entity_id = "path:scene_mood.foyer"

    graph.ingest_record(_record(record_id="knr-graph-1", turn_no=1, mood="潮湿"))
    graph.ingest_record(_record(record_id="knr-graph-2", turn_no=3, mood="警觉"))

    assert [
        fact["value"]
        for fact in graph.facts_for_entity(
            entity_id,
            session_id="s1",
            module_id="generic_mvp",
            as_of_turn=1,
        )
    ] == ["潮湿"]
    assert [
        fact["value"]
        for fact in graph.facts_as_of(
            entity_id,
            2,
            session_id="s1",
            module_id="generic_mvp",
        )
    ] == ["潮湿"]
    assert [
        fact["value"]
        for fact in graph.facts_as_of(
            entity_id,
            3,
            session_id="s1",
            module_id="generic_mvp",
        )
    ] == ["警觉"]


def test_graph_memory_search_is_scoped_and_includes_status_and_validity(tmp_path) -> None:
    graph = SQLiteNarrationGraphMemory(tmp_path / "narration-graph.sqlite3")

    graph.ingest_record(_record(record_id="s1-r1", session_id="s1", turn_no=1, mood="潮湿"))
    graph.ingest_record(_record(record_id="s2-r1", session_id="s2", turn_no=1, mood="潮湿"))
    graph.ingest_record(_record(record_id="s1-r2", session_id="s1", turn_no=2, mood="警觉"))

    assert graph.search_facts(
        "潮湿",
        session_id="s1",
        module_id="generic_mvp",
    ) == []

    s1_inactive = graph.search_facts(
        "潮湿",
        session_id="s1",
        module_id="generic_mvp",
        include_inactive=True,
    )
    s2_active = graph.search_facts(
        "潮湿",
        session_id="s2",
        module_id="generic_mvp",
    )

    assert len(s1_inactive) == 1
    assert s1_inactive[0]["session_id"] == "s1"
    assert s1_inactive[0]["status"] == "superseded"
    assert s1_inactive[0]["valid_from_turn"] == 1
    assert s1_inactive[0]["valid_to_turn"] == 2
    assert [fact["session_id"] for fact in s2_active] == ["s2"]
    assert [fact["status"] for fact in s2_active] == ["active"]


@pytest.mark.parametrize(
    ("path", "match"),
    [
        ("story_state.current_stage_id", "authoritative"),
        ("private_notes.foyer", "non-NarrativeState"),
    ],
)
def test_graph_memory_rejects_authoritative_or_non_narrative_paths(
    tmp_path,
    path: str,
    match: str,
) -> None:
    graph = SQLiteNarrationGraphMemory(tmp_path / "narration-graph.sqlite3")

    with pytest.raises(ValueError, match=match):
        graph.ingest_record(
            _record(
                record_id=f"bad-{path}",
                turn_no=1,
                mood="非法",
                path=path,
            )
        )

    assert graph.export_audit()["fact_count"] == 0


def test_graph_memory_rejects_missing_module_scope(tmp_path) -> None:
    graph = SQLiteNarrationGraphMemory(tmp_path / "narration-graph.sqlite3")
    record = _record(
        record_id="missing-module",
        turn_no=1,
        mood="潮湿",
    ).model_copy(
        update={"replay_input": {"packet": {}}},
        deep=True,
    )

    with pytest.raises(ValueError, match="session_id and module_id"):
        graph.ingest_record(record)

    assert graph.export_audit()["fact_count"] == 0


def test_graph_memory_close_and_context_manager_lifecycle(tmp_path) -> None:
    path = tmp_path / "narration-graph.sqlite3"

    with SQLiteNarrationGraphMemory(path) as graph:
        graph.ingest_record(_record(record_id="knr-graph-1", turn_no=1, mood="潮湿"))
        assert graph.export_audit()["fact_count"] == 1

    with pytest.raises(RuntimeError, match="closed"):
        graph.export_audit()

    reopened = SQLiteNarrationGraphMemory(path)
    try:
        assert reopened.export_audit()["fact_count"] == 1
    finally:
        reopened.close()

    reopened.close()

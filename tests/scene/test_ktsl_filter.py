from __future__ import annotations

from scenario.clues import ClueGraph, ModuleClue, SessionClueState
from scenario.ktsl.evaluate import evaluate_fixture
from scenario.ktsl.fixtures import list_ktsl_fixtures
from scenario.ktsl.filter import decide_info_access
from scenario.ktsl.models import ActorKnowledgeState, EventRecord, InfoLabel


def test_ktsl_full_filter_eliminates_public_sensitive_payload_leaks() -> None:
    for fixture in list_ktsl_fixtures():
        schedule_only = evaluate_fixture(fixture, "schedule_only")
        ktsl_full = evaluate_fixture(fixture, "ktsl_full")

        assert schedule_only.metrics.public_payload_leak_count > 0
        assert ktsl_full.metrics.public_payload_leak_count == 0
        assert all(
            not decision.leaked_public_payload
            for decision in ktsl_full.filter_decisions
        )


def test_ktsl_full_improves_filter_hypothesis_metrics_in_aggregate() -> None:
    schedule_only_results = [
        evaluate_fixture(fixture, "schedule_only") for fixture in list_ktsl_fixtures()
    ]
    ktsl_full_results = [
        evaluate_fixture(fixture, "ktsl_full") for fixture in list_ktsl_fixtures()
    ]

    schedule_only_unauthorized_or_leaks = sum(
        result.metrics.unauthorized_action_count
        + result.metrics.public_payload_leak_count
        for result in schedule_only_results
    )
    ktsl_full_unauthorized_or_leaks = sum(
        result.metrics.unauthorized_action_count
        + result.metrics.public_payload_leak_count
        for result in ktsl_full_results
    )

    assert schedule_only_unauthorized_or_leaks > ktsl_full_unauthorized_or_leaks
    assert all(
        result.metrics.declassification_completeness == 0.0
        for result in schedule_only_results
    )
    assert all(
        result.metrics.declassification_completeness == 1.0
        for result in ktsl_full_results
    )


def test_ktsl_filter_can_use_clue_graph_authorization_source() -> None:
    info = InfoLabel(
        id="info_archive",
        kind="know",
        scene_id="library",
        payload="The keeper-only archive payload.",
        sensitivity="high",
        public_payload="Archive reference.",
        redaction="A sensitive archive reference is redacted.",
    )
    event = EventRecord(
        id="event_archive",
        scene_id="library",
        action_id="inspect_archive",
        action_text="Inspect the archive",
        player_id="p1",
        character_id="investigator_1",
        output_info_ids=["info_archive"],
    )
    graph = ClueGraph(
        module_id="generic_mvp",
        clues=[
            ModuleClue(
                id="archive_index",
                title="Archive index",
                scene_id="library",
                info_id="info_archive",
                public_hint="The index names the archive.",
                private_payload="The keeper-only archive payload.",
                output_info_ids=["info_archive"],
                visible_to_player_ids=["p1"],
            )
        ],
    )
    clue_state = SessionClueState(
        clue_states={"archive_index": "delivered_by_fail_forward"}
    )

    decision = decide_info_access(
        info=info,
        event=event,
        character_id="investigator_1",
        player_id="p1",
        state=ActorKnowledgeState(character_id="investigator_1"),
        run_mode="ktsl_full",
        clue_graph=graph,
        session_clues=clue_state,
    )

    assert decision.status == "allowed"
    assert decision.authorized is True
    assert decision.reason_code == "clue_graph_authorized"
    assert "ClueGraph authorization source" in decision.reason
    assert "clue_id=archive_index" in decision.reason

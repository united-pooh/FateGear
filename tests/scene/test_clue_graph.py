"""Tests for clue graph coverage and fail-forward delivery."""

from __future__ import annotations

import pytest

from scenario.clues import (
    DISCOVERY_STATES,
    ClueEdge,
    ClueGraph,
    ModuleClue,
    SessionClueState,
)
from scenario.ktsl.models import ClueRecord


def _core_graph() -> ClueGraph:
    return ClueGraph(
        module_id="m1",
        core_route_ids=["ritual"],
        clues=[
            ModuleClue(
                id="archive_index",
                title="Archive index",
                scene_id="library",
                info_id="info_archive_index",
                public_hint="The archive index names the chapel ledger.",
                private_payload="The page also names the hidden cult sponsor.",
                route_ids=["ritual"],
                points_to_clue_ids=["chapel_ledger"],
                fail_forward_hint="A loose index card repeats the chapel ledger title.",
                output_info_ids=["info_chapel_ledger"],
                visible_to_player_ids=["p1"],
            ),
            ModuleClue(
                id="chapel_ledger",
                title="Chapel ledger",
                scene_id="chapel",
                info_id="info_chapel_ledger",
                public_hint="The ledger lists a midnight delivery.",
                private_payload="The delivery is a body moved by the mayor.",
                route_ids=["ritual"],
                prerequisite_clue_ids=["archive_index"],
                output_info_ids=["info_midnight_delivery"],
            ),
        ],
    )


def test_graph_derives_edges_and_reports_core_route_coverage() -> None:
    graph = _core_graph()
    state = SessionClueState()
    state.mark("archive_index", "discovered", turn=2)

    assert ("points_to", "archive_index", "chapel_ledger") in {
        (edge.kind, edge.source_clue_id, edge.target_clue_id)
        for edge in graph.all_edges()
    }

    coverage = graph.core_route_coverage(state)["ritual"]
    assert coverage.is_covered is True
    assert coverage.is_reachable is True
    assert coverage.covered_clue_ids == ["archive_index"]
    assert coverage.reachable_clue_ids == ["archive_index", "chapel_ledger"]


def test_all_required_discovery_states_are_supported() -> None:
    state = SessionClueState()
    for index, discovery_state in enumerate(DISCOVERY_STATES, start=1):
        state.mark(f"clue_{index}", discovery_state)
        assert state.state_for(f"clue_{index}") == discovery_state


def test_fail_forward_delivery_keeps_core_route_reachable_after_miss() -> None:
    graph = _core_graph()
    state = SessionClueState()

    plan = graph.plan_fail_forward_delivery(state, "archive_index")

    assert plan.core_routes_reachable is True
    assert plan.unresolved_core_route_ids == []
    assert len(plan.deliveries) == 1
    assert plan.deliveries[0].clue_id == "archive_index"
    assert plan.deliveries[0].via == "missed_hint"
    assert plan.deliveries[0].info_id == "info_archive_index"
    assert plan.route_coverage["ritual"].is_covered is True

    updated = state.apply_fail_forward_plan(plan, turn=3)
    assert updated.state_for("archive_index") == "delivered_by_fail_forward"
    assert updated.delivered_by_fail_forward == ["archive_index"]


def test_fail_forward_uses_route_alternative_when_primary_has_no_hint() -> None:
    graph = ClueGraph(
        module_id="m1",
        core_route_ids=["ritual"],
        clues=[
            ModuleClue(
                id="sealed_letter",
                title="Sealed letter",
                scene_id="library",
                info_id="info_letter",
                route_ids=["ritual"],
                redundant_with_clue_ids=["witness_echo"],
            ),
            ModuleClue(
                id="witness_echo",
                title="Witness echo",
                scene_id="street",
                info_id="info_letter_alt",
                public_hint="A witness remembers the same crest from the letter.",
                private_payload="The witness knows who carried it.",
                route_ids=["ritual"],
                fail_forward_route_ids=["ritual"],
            ),
        ],
    )

    plan = graph.plan_fail_forward_delivery(SessionClueState(), "sealed_letter")

    assert plan.core_routes_reachable is True
    assert [(d.clue_id, d.via) for d in plan.deliveries] == [
        ("witness_echo", "redundant_clue")
    ]
    assert plan.route_coverage["ritual"].covered_clue_ids == ["witness_echo"]


def test_player_view_does_not_leak_private_payload_to_unauthorized_player() -> None:
    graph = _core_graph()
    state = SessionClueState(clue_states={"archive_index": "discovered"})

    unauthorized = graph.player_view(state, player_id="p2")
    authorized = graph.player_view(state, player_id="p1")
    keeper = graph.keeper_view(state)

    assert unauthorized == []
    assert len(authorized) == 1
    player_dump = authorized[0].model_dump()
    assert player_dump["public_hint"] == "The archive index names the chapel ledger."
    assert "private_payload" not in player_dump
    assert "hidden cult sponsor" not in authorized[0].model_dump_json()
    assert keeper[0].private_payload == "The page also names the hidden cult sponsor."


def test_module_clue_can_map_from_ktsl_clue_record() -> None:
    record = ClueRecord(
        id="clue_archive",
        scene_id="library",
        info_id="info_archive",
        title="Archive scrap",
        public_hint="A scrap points at the index.",
        keeper_detail="The scrap is planted by the antagonist.",
        required_info_ids=["info_basement"],
        output_info_ids=["info_archive"],
    )

    clue = ModuleClue.from_ktsl_record(record)

    assert clue.info_id == "info_archive"
    assert clue.private_payload == "The scrap is planted by the antagonist."
    assert clue.required_info_ids == ["info_basement"]
    assert clue.prerequisite_clue_ids == []
    assert clue.output_info_ids == ["info_archive"]


def test_invalid_edge_refs_are_rejected() -> None:
    with pytest.raises(ValueError, match="not in clues"):
        ClueGraph(
            module_id="m1",
            clues=[
                ModuleClue(id="a", title="A", scene_id="s"),
            ],
            edges=[
                ClueEdge(
                    kind="points_to",
                    source_clue_id="a",
                    target_clue_id="missing",
                )
            ],
        )

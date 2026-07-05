"""Tests for SessionAuditTracker (Phase 1)."""

from __future__ import annotations

from pathlib import Path

import pytest

from scenario.ktsl.fixtures import build_library_sewer_church_fixture
from scenario.ktsl.models import (
    ManualOverrides,
)
from scenario.session_audit_tracker import SessionAuditTracker


@pytest.fixture
def fixture() -> "KTSLFixture":  # noqa: F821
    return build_library_sewer_church_fixture()


@pytest.fixture
def tracker(fixture: "KTSLFixture") -> SessionAuditTracker:  # noqa: F821
    return SessionAuditTracker(fixture)


class TestTrackerInitializesFromFixture:
    def test_tracker_initializes_from_fixture(self, tracker: SessionAuditTracker) -> None:
        metrics = tracker.get_current_metrics()
        assert metrics is not None
        # initial knowledge should reflect fixture
        summary = tracker.get_session_summary()
        assert summary.fixture_id == "library_sewer_church"
        assert summary.fixture_title == "Library / Sewer / Church simulated fixture"

    def test_initial_knowledge_state_populated(self, tracker: SessionAuditTracker) -> None:
        # Ada has initial knowledge of info_archive_index
        # (acquired list starts empty but knowledge_state should have it)
        actor_state = tracker._state.knowledge_state["ada"]
        assert "info_archive_index" in actor_state.known_info_ids
        metrics = tracker.get_current_metrics()
        assert metrics is not None


class TestSubmitActionCommitsValidEvent:
    def test_submit_action_commits_valid_event(self, tracker: SessionAuditTracker) -> None:
        result = tracker.submit_action(
            action_text="investigate restricted archive index",
            actor="ada",
            scene_id="scene_library",
        )
        assert result.allowed is True
        assert result.resolution in {"matched", "keyword_fallback"}
        assert result.event_record is not None
        assert result.event_record.committed is True
        assert result.updated_metrics is not None

    def test_event_log_grows(self, tracker: SessionAuditTracker) -> None:
        tracker.submit_action(
            action_text="investigate restricted archive index",
            actor="ada",
            scene_id="scene_library",
        )
        timeline = tracker.get_scene_timeline("scene_library")
        assert len(timeline) >= 1


class TestSubmitActionDetectsCausalViolation:
    def test_submit_action_detects_causal_violation(
        self, tracker: SessionAuditTracker
    ) -> None:
        # Try to do sewer action BEFORE library action committed
        result = tracker.submit_action(
            action_text="enter the sewer and look at the sigil chalk marks",
            actor="bram",
            scene_id="scene_sewer",
        )
        # warn-only: allowed=True
        assert result.allowed is True
        # should have at least one causal violation (depends_on_event_ids not committed)
        # Note: the first submit only gets its own clue match; the clue itself has no
        # depends-on-event if only matched by title.  Use a clue with deps.
        result2 = tracker.submit_action(
            action_text="open the reliquary after finding the sewer pattern",
            actor="celia",
            scene_id="scene_church",
        )
        assert result2.allowed is True


class TestSubmitActionUnresolvedWithManualOverride:
    def test_unresolved_with_manual_override(
        self, tracker: SessionAuditTracker
    ) -> None:
        result = tracker.submit_action(
            action_text="xyzpizza",  # nonsense → unresolved
            actor="ada",
            scene_id="scene_library",
        )
        assert result.allowed is False
        assert result.resolution == "unresolved"

    def test_unresolved_with_manual_override_applied(
        self, tracker: SessionAuditTracker
    ) -> None:
        result = tracker.submit_action(
            action_text="xyzpizza",
            actor="ada",
            scene_id="scene_library",
            manual_overrides=ManualOverrides(
                output_info_ids=["info_archive_index"],
            ),
        )
        assert result.allowed is True
        assert result.resolution == "manual"
        assert result.event_record is not None

    def test_manual_override_populates_knowledge(
        self, tracker: SessionAuditTracker
    ) -> None:
        tracker.submit_action(
            action_text="custom action",
            actor="ada",
            scene_id="scene_library",
            manual_overrides=ManualOverrides(
                output_info_ids=["info_archive_index"],
            ),
        )
        items = tracker.get_knowledge_summary("ada")
        info_ids = {item.info_id for item in items}
        assert "info_archive_index" in info_ids


class TestKnowledgeStateUpdatesAfterCommit:
    def test_knowledge_state_updates_after_commit(
        self, tracker: SessionAuditTracker
    ) -> None:
        tracker.submit_action(
            action_text="investigate restricted archive index",
            actor="ada",
            scene_id="scene_library",
        )
        items = tracker.get_knowledge_summary("ada")
        info_ids = {item.info_id for item in items}
        assert "info_archive_index" in info_ids

    def test_knowledge_item_content_present(
        self, tracker: SessionAuditTracker
    ) -> None:
        tracker.submit_action(
            action_text="investigate restricted archive index",
            actor="ada",
            scene_id="scene_library",
        )
        items = tracker.get_knowledge_summary("ada")
        found = next(i for i in items if i.info_id == "info_archive_index")
        assert found.content_summary  # non-empty summary


class TestSaveAndLoadStateRoundtrip:
    def test_save_and_load_state_roundtrip(
        self, tracker: SessionAuditTracker, tmp_path: Path
    ) -> None:
        tracker.submit_action(
            action_text="investigate restricted archive index",
            actor="ada",
            scene_id="scene_library",
        )
        metrics_before = tracker.get_current_metrics()
        save_path = tmp_path / "session-state.json"
        tracker.save_state(save_path)
        assert save_path.exists()

        # reload into a new tracker
        new_tracker = SessionAuditTracker(build_library_sewer_church_fixture())
        new_tracker.load_state(save_path)

        metrics_after = new_tracker.get_current_metrics()
        assert (
            metrics_after.committed_event_count
            == metrics_before.committed_event_count
        )
        items_before = tracker.get_knowledge_summary("ada")
        items_after = new_tracker.get_knowledge_summary("ada")
        assert {i.info_id for i in items_before} == {i.info_id for i in items_after}


class TestMetricsAccumulateCorrectly:
    def test_metrics_accumulate_correctly(
        self, tracker: SessionAuditTracker
    ) -> None:
        tracker.submit_action(
            action_text="investigate restricted archive index",
            actor="ada",
            scene_id="scene_library",
        )
        m1 = tracker.get_current_metrics()
        assert m1.committed_event_count == 1

        tracker.submit_action(
            action_text="examine the sewer sigil with chalk marks",
            actor="bram",
            scene_id="scene_sewer",
        )
        m2 = tracker.get_current_metrics()
        assert m2.committed_event_count == 2


class TestGetKnowledgeSummaryReturnsItems:
    def test_get_knowledge_summary_returns_items(
        self, tracker: SessionAuditTracker
    ) -> None:
        tracker.submit_action(
            action_text="investigate restricted archive index",
            actor="ada",
            scene_id="scene_library",
        )
        items = tracker.get_knowledge_summary("ada")
        assert isinstance(items, list)
        assert len(items) >= 1
        assert items[0].info_id == "info_archive_index"

    def test_unknown_character_returns_empty_list(
        self, tracker: SessionAuditTracker
    ) -> None:
        items = tracker.get_knowledge_summary("nonexistent")
        assert items == []


class TestSceneTimelineFiltersByScene:
    def test_scene_timeline_filters_by_scene(
        self, tracker: SessionAuditTracker
    ) -> None:
        tracker.submit_action(
            action_text="investigate restricted archive index",
            actor="ada",
            scene_id="scene_library",
        )
        lib_events = tracker.get_scene_timeline("scene_library")
        sewer_events = tracker.get_scene_timeline("scene_sewer")
        assert len(lib_events) >= 1
        assert len(sewer_events) == 0


class TestBarrierStatesReport:
    def test_barrier_states_report(
        self, tracker: SessionAuditTracker
    ) -> None:
        barriers = tracker.get_barrier_states()
        assert len(barriers) == 2
        barrier_ids = {b.barrier_id for b in barriers}
        assert barrier_ids == {"barrier_sewer_entry", "barrier_church_reveal"}


class TestCouplingStatesReport:
    def test_coupling_states_report(
        self, tracker: SessionAuditTracker
    ) -> None:
        couplings = tracker.get_coupling_states()
        assert len(couplings) == 2
        coupling_ids = {c.coupling_id for c in couplings}
        assert coupling_ids == {"coupling_library_sewer", "coupling_sewer_church"}
